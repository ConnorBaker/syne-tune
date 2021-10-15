"""
Example showing how to run on Sagemaker with a custom docker image.
"""
import logging
from pathlib import Path

from sagemaker_tune.backend.sagemaker_backend.custom_framework import CustomFramework
from sagemaker_tune.backend.sagemaker_backend.sagemaker_backend import SagemakerBackend
from sagemaker_tune.backend.sagemaker_backend.sagemaker_utils import get_execution_role
from sagemaker_tune.optimizer.schedulers.fifo import FIFOScheduler
from sagemaker_tune.tuner import Tuner
from sagemaker_tune.search_space import randint
from sagemaker_tune.stopping_criterion import StoppingCriterion


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)

    random_seed = 31415927
    max_steps = 100
    n_workers = 4

    config_space = {
        "steps": max_steps,
        "width": randint(0, 20),
        "height": randint(-100, 100)
    }
    entry_point = str(
        Path(__file__).parent / "training_scripts" / "height_example" /
        "train_height.py")
    mode = "min"
    metric = "mean_loss"

    # Random search without stopping
    scheduler = FIFOScheduler(
        config_space,
        searcher='random',
        mode=mode,
        metric=metric,
        random_seed=random_seed)

    # indicate here an image_uri that is available in ecr, something like that "XXXXXXXXXXXX.dkr.ecr.us-west-2.amazonaws.com/my_image:latest"
    image_uri = ...

    backend = SagemakerBackend(
        sm_estimator=CustomFramework(
            entry_point=entry_point,
            instance_type="ml.m5.large",
            instance_count=1,
            role=get_execution_role(),
            image_uri=image_uri,
            max_run=10 * 60,
            job_name_prefix='hpo-hyperband',
        ),
        # names of metrics to track. Each metric will be detected by Sagemaker if it is written in the
        # following form: "[RMSE]: 1.2", see in train_main_example how metrics are logged for an example
        metrics_names=[metric],
    )

    stop_criterion = StoppingCriterion(max_wallclock_time=600)
    tuner = Tuner(
        backend=backend,
        scheduler=scheduler,
        stop_criterion=stop_criterion,
        n_workers=n_workers,
        sleep_time=5.0,
    )

    tuner.run()