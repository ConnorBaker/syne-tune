import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
import os

import boto3

from sagemaker_tune.backend.sagemaker_backend.estimator_factory import \
    sagemaker_estimator_factory
from sagemaker_tune.backend.sagemaker_backend.sagemaker_utils import \
    add_sagemaker_tune_dependency, get_execution_role
from sagemaker_tune.tuner import Tuner
from sagemaker_tune.util import s3_experiment_path

import sagemaker_tune


class RemoteLauncher:
    def __init__(
            self,
            tuner: Tuner,
            role: Optional[str] = None,
            instance_type: str = "ml.m5.xlarge",
            dependencies: Optional[List[str]] = None,
            framework: Optional[str] = None,
            estimator_kwargs: Optional[dict] = None,
            store_logs_localbackend: bool = False,
            log_level: Optional[int] = None,
            s3_path: Optional[str] = None,
            no_tuner_logging: bool = False,
    ):
        """
        This class allows to launch a tuning job remotely
        The remote tuning job may use either the local backend (in which case the remote
        instance will be used to evaluate trials) or the Sagemaker backend in which case the remote instance
        will spawn one Sagemaker job per trial.

        :param tuner: Tuner that should be run remotely on a `instance_type` instance. Note that StoppingCriterion
        should be used for the Tuner rather than a lambda function to ensure serialization.
        :param role: sagemaker role to be used to launch the remote tuning instance.
        :param instance_type: instance where the tuning is going to happen.
        :param dependencies: list of folders that should be included as dependencies for the backend script to run
        :param framework: SageMaker framework used for the tuning code. If the
            local backend is used, this should be the framework required by the
            training script. Default is PyTorch.
            NOTE: SkLearn as default may be a more lightweight choice
        :param estimator_kwargs: Extra arguments for creating the SageMaker
            estimator for the tuning code. Depends on framework
        :param store_logs_localbackend: whether to store logs of trials when using the local backend.
            When using Sagemaker backend, logs are persisted by Sagemaker.
        :param log_level: Logging level. Default is logging.INFO, while
            logging.DEBUG gives more messages
        :param s3_path: S3 base path used for checkpointing. The full path
            also involves the tuner name
        :param no_tuner_logging: If True, the logging level for
            sagemaker_tune.tuner is set to ERROR
        """
        assert not self.is_lambda(tuner.stop_criterion), \
            "remote launcher does not support using lambda functions for stopping criterion. Use StoppingCriterion, " \
            "with Tuner if you want to use the remote launcher. See launch_height_sagemaker_remotely.py for" \
            " a full example."
        self.tuner = tuner
        self.role = get_execution_role() if role is None else role
        self.instance_type = instance_type
        self.base_job_name = f"smtr-{tuner.name}"
        if dependencies is not None:
            for dep in dependencies:
                assert Path(dep).exists(), f"dependency {dep} was not found."
        self.dependencies = dependencies
        if framework is None:
            framework = 'PyTorch'
        self.framework = framework
        if estimator_kwargs is None:
            estimator_kwargs = dict()
        k = 'framework_version'
        if self.framework == 'PyTorch' and k not in estimator_kwargs:
            estimator_kwargs[k] = '1.6'
        self.estimator_kwargs = estimator_kwargs
        self.store_logs_localbackend = store_logs_localbackend
        self.log_level = log_level
        if s3_path is None:
            s3_path = s3_experiment_path()
        self.s3_path = s3_path
        assert isinstance(no_tuner_logging, bool)
        self.no_tuner_logging = str(no_tuner_logging)

    def is_lambda(self, f):
        """
        :param f:
        :return: True iff f is a lambda function
        """
        try:
            return callable(f) and f.__name__ == "<lambda>"
        except AttributeError:
            return False

    def run(
            self,
            wait: bool = True,
    ):
        """
        :param wait: Whether the call should wait until the job completes (default: True). If False the call returns
        once the tuning job is scheduled on Sagemaker.
        :return:
        """
        self.prepare_upload()

        if 'AWS_DEFAULT_REGION' not in os.environ:
            # launching in this is needed to send a default configuration on the tuning loop running on Sagemaker
            # todo restore the env variable if present to avoid a side effect
            os.environ['AWS_DEFAULT_REGION'] = 'us-west-2'
        self.launch_tuning_job_on_sagemaker(wait=wait)

    def prepare_upload(self):
        """
        Prepares the files that needs to be uploaded by Sagemaker so that the Tuning job can happen.
        This includes, 1) the entrypoint script of the backend and 2) the tuner that needs to run
        remotely.
        :return:
        """
        upload_dir = str(self.upload_dir())
        shutil.rmtree(upload_dir, ignore_errors=True)

        # Save entrypoint script and content in a folder to be send by sagemaker.
        # This is required so that the entrypoint is found on Sagemaker.
        source_dir = str(self.get_source_dir())
        logging.info(f"copy endpoint files from {source_dir} to {upload_dir}")
        shutil.copytree(source_dir, upload_dir)

        backup = str(self.tuner.backend.entrypoint_path())

        # update the path of the endpoint script so that it can be found when launching remotely
        self.update_backend_with_remote_paths()

        # save tuner
        self.tuner.save(upload_dir)

        # avoid side effect
        self.tuner.backend.set_entrypoint(backup)

        # todo clean copy of remote dir
        tgt_requirement = self.remote_script_dir() / "requirements.txt"
        try:
            os.remove(tgt_requirement)
        except OSError:
            pass
        endpoint_requirements = self.tuner.backend.entrypoint_path().parent / "requirements.txt"
        if endpoint_requirements.exists():
            logging.info(f"copy endpoint script requirements to {self.remote_script_dir()}")
            shutil.copy(endpoint_requirements, tgt_requirement)
            pass


    def get_source_dir(self) -> Path:
        # note: this logic would be better moved to the backend.
        if self.is_source_dir_specified():
            return Path(self.tuner.backend.source_dir)
        else:
            return Path(self.tuner.backend.entrypoint_path()).parent

    def is_source_dir_specified(self) -> bool:
        return hasattr(self.tuner.backend, "source_dir") and self.tuner.backend.sm_estimator.source_dir is not None

    def update_backend_with_remote_paths(self):
        """
        Update the paths of the backend of the endpoint script and source dir with their remote location.
        """
        if self.is_source_dir_specified():
            # the source_dir is deployed to `upload_dir`
            self.tuner.backend.sm_estimator.source_dir = str(Path(self.upload_dir().name))
        else:
            self.tuner.backend.set_entrypoint(
                f"{self.upload_dir().name}/{self.tuner.backend.entrypoint_path().name}")

    def upload_dir(self) -> Path:
        return Path(sagemaker_tune.__path__[0]).parent / "tuner"

    def remote_script_dir(self) -> Path:
        return Path(__file__).parent

    def launch_tuning_job_on_sagemaker(self, wait: bool):
        # todo add Sagemaker cloudwatch metrics to visualize live results of tuning best results found over time.
        if self.instance_type != "local":
            checkpoint_s3_uri = f"{self.s3_path}/{self.tuner.name}/"
            logging.info(f"Tuner will checkpoint results to {checkpoint_s3_uri}")
        else:
            # checkpointing is not supported in local mode. When using local mode with remote tuner (for instance for
            # debugging), results are not stored.
            checkpoint_s3_uri = None
        # Create SM estimator for tuning code
        hyperparameters = {
            "tuner_path": f"{self.upload_dir().name}/",
            "store_logs": self.store_logs_localbackend,
            "no_tuner_logging": self.no_tuner_logging,
        }
        if self.log_level is not None:
            hyperparameters['log_level'] = self.log_level
        factory_kwargs = dict(
            self.estimator_kwargs,
            entry_point="remote_main.py",
            instance_type=self.instance_type,
            framework=self.framework,
            role=self.role,
            source_dir=str(self.remote_script_dir()),
            image_uri=self.sagemaker_tune_image_uri(),
            hyperparameters=hyperparameters,
            checkpoint_s3_uri=checkpoint_s3_uri,
        )
        tuner_estimator = sagemaker_estimator_factory(**factory_kwargs)
        add_sagemaker_tune_dependency(tuner_estimator)

        # ask Sagemaker to send the path containing entrypoint script and tuner.
        tuner_estimator.dependencies.append(str(self.upload_dir()))

        if self.dependencies is not None:
            tuner_estimator.dependencies += self.dependencies

        # launches job on Sagemaker
        return tuner_estimator.fit(wait=wait, job_name=self.tuner.name)

    def sagemaker_tune_image_uri(self) -> str:
        """
        :return: sagemaker tune docker uri, if not present try to build it and returns an error if this failed.
        """
        docker_image_name = "smt-cpu-py36"
        account_id = boto3.client("sts").get_caller_identity()["Account"]
        image_uri = f"{account_id}.dkr.ecr.us-west-2.amazonaws.com/{docker_image_name}"
        try:
            logging.info(f"Fetching sagemaker tune image {image_uri}")
            boto3.client("ecr").list_images(repositoryName=docker_image_name)
        except Exception:
            # todo RepositoryNotFoundException should be caught but I did not manage to import it
            logging.warning(
                f"Docker-image of sagemaker-tune {docker_image_name} could not be found, run \n"
                f"`cd {Path(__file__).parent}/container; bash build_sagemaker_tune_container.sh`\n"
                f"in a terminal to build it. Trying to do it now."
            )
            subprocess.run("./build_sagemaker_tune_container.sh",
                           cwd=Path(sagemaker_tune.__path__[0]).parent / "container")
            logging.info(f"attempting to fetch {docker_image_name} again.")
            boto3.client("ecr").list_images(repositoryName=docker_image_name)

        return image_uri