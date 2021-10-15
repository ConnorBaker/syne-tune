from typing import Iterable, List, Type, Optional
import numpy as np
from scipy.optimize import fmin_l_bfgs_b
import logging
from numpy.random import RandomState

from sagemaker_tune.optimizer.schedulers.searchers.bayesopt.tuning_algorithms.base_classes \
    import SurrogateModel, ScoringFunction, LocalOptimizer, \
    SurrogateOutputModel, AcquisitionClassAndArgs, \
    unwrap_acquisition_class_and_kwargs
from sagemaker_tune.optimizer.schedulers.searchers.bayesopt.datatypes.common \
    import Configuration
from sagemaker_tune.optimizer.schedulers.searchers.bayesopt.datatypes.hp_ranges \
    import HyperparameterRanges

logger = logging.getLogger(__name__)


class IndependentThompsonSampling(ScoringFunction):
    """
    Note: This is not Thompson sampling, but rather a variant called
    "independent Thompson sampling", where means and variances are drawn
    from the marginal rather than the joint distribution. This is cheap,
    but incorrect.

    """
    def __init__(
            self, model: SurrogateModel,
            random_state: Optional[RandomState] = None):
        self.model = model
        if random_state is None:
            random_state = RandomState(31415629)
        self.random_state = random_state

    def score(self, candidates: Iterable[Configuration],
              model: Optional[SurrogateModel] = None) -> List[float]:
        if model is None:
            model = self.model
        predictions_list = model.predict_candidates(candidates)
        scores = []
        # If the model supports fantasizing, posterior_means is a matrix. In
        # that case, samples are drawn for every column, then averaged (why
        # we need np.mean)
        for predictions in predictions_list:
            posterior_means = predictions['mean']
            posterior_stds = predictions['std']
            new_score = [
                np.mean(self.random_state.normal(m, s))
                for m, s in zip(posterior_means, posterior_stds)]
            scores.append(new_score)
        return list(np.mean(np.array(scores), axis=0))


class LBFGSOptimizeAcquisition(LocalOptimizer):
    def __init__(
            self, hp_ranges: HyperparameterRanges, model: SurrogateOutputModel,
            acquisition_class: AcquisitionClassAndArgs,
            active_metric: str = None):
        super().__init__(hp_ranges, model, acquisition_class, active_metric)
        # Number criterion evaluations in last recent optimize call
        self.num_evaluations = None

    def optimize(self, candidate: Configuration,
                 model: Optional[SurrogateOutputModel] = None) -> Configuration:
        # Before local minimization, the model for this state_id should have been fitted.
        if model is None:
            model = self.model
        acquisition_class, acquisition_kwargs = unwrap_acquisition_class_and_kwargs(
            self.acquisition_class)
        acquisition_function = acquisition_class(
            model, self.active_metric, **acquisition_kwargs)

        x0 = self.hp_ranges.to_ndarray(candidate)
        bounds = self.hp_ranges.get_ndarray_bounds()
        n_evaluations = [0]  # wrapped in list to allow access from function

        # unwrap 2d arrays
        def f_df(x):
            n_evaluations[0] += 1
            return acquisition_function.compute_acq_with_gradient(x)

        res = fmin_l_bfgs_b(f_df, x0=x0, bounds=bounds, maxiter=1000)
        self.num_evaluations = n_evaluations[0]
        if res[2]['task'] == b'ABNORMAL_TERMINATION_IN_LNSRCH':
            # this condition was copied from the old GPyOpt code
            logger.warning(
                f"ABNORMAL_TERMINATION_IN_LNSRCH in lbfgs after {n_evaluations[0]} evaluations, "
                "returning original candidate"
            )
            return candidate  # returning original candidate
        else:
            # Clip to avoid situation where result is small epsilon out of bounds
            a_min, a_max = zip(*bounds)
            optimized_x = np.clip(res[0], a_min, a_max)
            # Make sure the above clipping does really just fix numerical rounding issues in LBFGS
            # if any bigger change was made there is a bug and we want to throw an exception
            assert np.linalg.norm(res[0] - optimized_x) < 1e-6, (res[0], optimized_x, bounds)
            result = self.hp_ranges.from_ndarray(optimized_x.flatten())
            return result


class NoOptimization(LocalOptimizer):
    def optimize(self, candidate: Configuration,
                 model: Optional[SurrogateModel] = None) -> Configuration:
        return candidate