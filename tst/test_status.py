import time
from datetime import datetime

from sagemaker_tune.backend.trial_status import Trial, Status
from sagemaker_tune.tuning_status import TuningStatus, print_best_metric_found


def test_status():
    metric_names = ['NLL', 'time']
    status = TuningStatus(metric_names=metric_names, metric_mode='min')

    trial0 = Trial(trial_id=0, config={"x": 1.0}, creation_time=None)
    trial1 = Trial(trial_id=1, config={"x": 5.0}, creation_time=None)
    status.update(
        trial_status_dict={
            0: (trial0, Status.in_progress),
            1: (trial1, Status.in_progress),
        },
        new_results=[
            (0, {"NLL": 2.0, "time": 10.0}),
            (0, {"NLL": 1.0, "time": 12.0 }),
            (1, {"NLL": 3.0, "time": 5.0}),
        ]
    )
    assert status.overall_metric_statistics.max_metrics
    assert status.num_trials_started == 2
    assert status.overall_metric_statistics.max_metrics == {'NLL': 3.0, 'time': 12.0}
    assert status.overall_metric_statistics.min_metrics == {'NLL': 1.0, 'time': 5.0}
    assert status.overall_metric_statistics.sum_metrics == {'NLL': 6.0, 'time': 27.0}

    assert status.trial_metric_statistics[0].max_metrics == {'NLL': 2.0, 'time': 12.0}
    assert status.trial_metric_statistics[0].min_metrics == {'NLL': 1.0, 'time': 10.0}
    assert status.trial_metric_statistics[0].sum_metrics == {'NLL': 3.0, 'time': 22.0}

    status.update(
        trial_status_dict={
            0: (trial0, Status.in_progress),
        },
        new_results=[
            (0, {"NLL": 0.0, "time": 20.0}),
        ]
    )
    assert status.trial_metric_statistics[0].max_metrics == {'NLL': 2.0, 'time': 20.0}
    assert status.trial_metric_statistics[0].min_metrics == {'NLL': 0.0, 'time': 10.0}
    assert status.trial_metric_statistics[0].sum_metrics == {'NLL': 3.0, 'time': 42.0}

    print(str(status))

    best_trialid, best_metric = print_best_metric_found(
        tuning_status=status,
        metric_names=metric_names,
        mode='min',
    )
    assert best_trialid == 0
    assert best_metric == 0.0

    best_trialid, best_metric = print_best_metric_found(
        tuning_status=status,
        metric_names=metric_names,
        mode='max',
    )
    assert best_trialid == 1
    assert best_metric == 3.0