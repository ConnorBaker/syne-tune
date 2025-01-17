# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
import logging
from pathlib import Path

from sagemaker.sklearn import SKLearn

from syne_tune.backend import SageMakerBackend
from syne_tune.backend.sagemaker_backend.sagemaker_utils import (
    get_execution_role,
    default_sagemaker_session,
)
from syne_tune.optimizer.baselines import ASHA
from syne_tune import Tuner, StoppingCriterion
from syne_tune.config_space import randint


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    random_seed = 31415927
    max_steps = 100
    n_workers = 4
    delete_checkpoints = True
    max_wallclock_time = 10 * 60

    mode = "min"
    metric = "mean_loss"
    resource_attr = "epoch"
    max_resource_attr = "steps"
    config_space = {
        max_resource_attr: max_steps,
        "width": randint(0, 20),
        "height": randint(-100, 100),
    }
    entry_point = (
        Path(__file__).parent
        / "training_scripts"
        / "checkpoint_example"
        / "train_height_checkpoint.py"
    )

    # ASHA promotion
    scheduler = ASHA(
        config_space,
        metric=metric,
        mode=mode,
        max_resource_attr=max_resource_attr,
        resource_attr=resource_attr,
        type="promotion",
        search_options={"debug_log": True},
    )
    # SageMaker backend: We use the warm pool feature here
    trial_backend = SageMakerBackend(
        sm_estimator=SKLearn(
            entry_point=str(entry_point),
            instance_type="ml.c5.4xlarge",
            instance_count=1,
            role=get_execution_role(),
            max_run=10 * 60,
            framework_version="1.0-1",
            py_version="py3",
            sagemaker_session=default_sagemaker_session(),
            disable_profiler=True,
            debugger_hook_config=False,
            keep_alive_period_in_seconds=300,  # warm pool feature
        ),
        metrics_names=[metric],
        delete_checkpoints=delete_checkpoints,
    )

    stop_criterion = StoppingCriterion(max_wallclock_time=max_wallclock_time)
    tuner = Tuner(
        trial_backend=trial_backend,
        scheduler=scheduler,
        stop_criterion=stop_criterion,
        n_workers=n_workers,
        sleep_time=5.0,
        tuner_name="height-sagemaker-checkpoints",
        start_jobs_without_delay=False,
    )

    tuner.run()
