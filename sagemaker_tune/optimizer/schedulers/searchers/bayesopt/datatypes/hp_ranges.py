from abc import ABC, abstractmethod
from typing import Tuple, List, Iterable, Dict
import numpy as np
from numpy.random import RandomState

from sagemaker_tune.search_space import Domain, Categorical
from sagemaker_tune.search_space import non_constant_hyperparameter_keys
from sagemaker_tune.optimizer.schedulers.searchers.bayesopt.datatypes.common \
    import Hyperparameter, Configuration

__all__ = ['HyperparameterRanges']


def _filter_constant_hyperparameters(config_space: Dict) -> Dict:
    nonconst_keys = set(non_constant_hyperparameter_keys(config_space))
    return {k: v for k, v in config_space.items() if k in nonconst_keys}


def _ndarray_size(config_space: Dict) -> int:
    size = 0
    for name, hp_range in config_space.items():
        assert isinstance(hp_range, Domain)
        if isinstance(hp_range, Categorical):
            size += len(hp_range.categories)
        else:
            size += 1
    return size


class HyperparameterRanges(ABC):
    def __init__(self, config_space: Dict, name_last_pos: str = None,
                 value_for_last_pos=None):
        """
        If name_last_pos is given, the hyperparameter of that name is assigned
        the final position in the vector returned by `to_ndarray`. This can be
        used to single out the (time) resource for a GP model, where that
        component has to come last.

        If in this case (name_last_pos given), value_for_last_pos is also given,
        some methods are modified:
        - `random_config` samples a config as normal, but then overwrites the
          name_last_pos component by value_for_last_pos
        - `get_ndarray_bounds` works as normal, but returns bound (a, a) for
          name_last_pos component, where a is the internal value corresponding
          to value_for_last_pos
        The use case is HPO with a resource attribute. This attribute should be
        fixed when optimizing the acquisition function, but can take different
        values in the evaluation data (coming from all previous searches).

        :param config_space: Configuration space. Constant hyperparameters are
            filtered out here
        """
        self.config_space = _filter_constant_hyperparameters(config_space)
        self.name_last_pos = name_last_pos
        self.value_for_last_pos = value_for_last_pos
        self._ndarray_size = _ndarray_size(self.config_space)
        self._set_internal_keys()

    def _set_internal_keys(self):
        keys = sorted(self.config_space.keys())
        if self.name_last_pos is not None:
            assert self.name_last_pos in keys, \
                f"name_last_pos = '{self.name_last_pos}' not among " +\
                f"hyperparameter names [{keys}]"
            pos = keys.index(self.name_last_pos)
            keys = keys[:pos] + keys[(pos + 1):] + [self.name_last_pos]
        self._internal_keys = keys

    @property
    def internal_keys(self) -> List[str]:
        return self._internal_keys

    @abstractmethod
    def to_ndarray(self, config: Configuration) -> np.ndarray:
        """
        Categorical values are one-hot encoded.

        :param config: Config to encode
        :return: Encoded HP vector
        """
        pass

    def to_ndarray_matrix(
            self, configs: Iterable[Configuration]) -> np.ndarray:
        return np.vstack(
            [self.to_ndarray(config) for config in configs])

    def ndarray_size(self) -> int:
        """
        Default assumes that each categorical HP is one-hot encoded.
        :return: Dimensionality of encoded HP vector returned by `to_ndarray`
        """
        return self._ndarray_size

    @abstractmethod
    def from_ndarray(self, enc_config: np.ndarray) -> Configuration:
        """
        Converts a config from internal ndarray representation (fed to the
        GP) to its external (dict) representation. This typically involves
        rounding.
        """
        pass

    def is_attribute_fixed(self):
        return (self.name_last_pos is not None) and \
               (self.value_for_last_pos is not None)

    def _fix_attribute_value(self, name):
        return self.is_attribute_fixed() and name == self.name_last_pos

    def _transform_config(self, config: Configuration):
        if self.is_attribute_fixed():
            config[self.name_last_pos] = self.value_for_last_pos
        return config

    def _random_config(self, random_state: RandomState) -> Configuration:
        return {k: v.sample(random_state=random_state)
                for k, v in self.config_space.items()}

    def random_config(self, random_state: RandomState) -> Configuration:
        return self._transform_config(self._random_config(random_state))

    def _random_configs(self, random_state: RandomState,
                        num_configs: int) -> List[Configuration]:
        return [self._random_config(random_state) for _ in range(num_configs)]

    def random_configs(self, random_state, num_configs: int) -> \
            List[Configuration]:
        return [
            self._transform_config(config) for config in self._random_configs(
                random_state, num_configs)]

    @abstractmethod
    def get_ndarray_bounds(self) -> List[Tuple[float, float]]:
        """
        Returns (lower, upper) bounds for each dimension in ndarray vector
        representation.
        """
        pass

    @abstractmethod
    def __repr__(self) -> str:
        pass

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        pass

    def __len__(self) -> int:
        return len(self.config_space)

    def filter_for_last_pos_value(self, configs: List[Configuration]) -> List[Configuration]:
        """
        If is_attribute_fixed, `configs` is filtered by removing
        entries whose name_last_pos attribute value is different from
        value_for_last_pos. Otherwise, it is returned unchanged.

        """
        if self.is_attribute_fixed():
            configs = [
                config for config in configs
                if config[self.name_last_pos] == self.value_for_last_pos]
        return configs

    def config_to_tuple(
            self, config: Configuration, keys=None,
            skip_last: bool = False) -> Tuple[Hyperparameter, ...]:
        """
        :param config: Configuration
        :param keys: Overrides `_internal_keys`
        :param skip_last: If True and `name_last_pos` is used, the
            corresponding attribute is skipped, so that config and
            tuple are non-extended
        :return: Tuple representation
        """
        if keys is None:
            keys = self.internal_keys
            if skip_last and self.name_last_pos is not None:
                keys = keys[:-1]  # Skip last pos
        return tuple(config[k] for k in keys)

    def tuple_to_config(
            self, config_tpl: Tuple[Hyperparameter, ...], keys=None,
            skip_last: bool = False) -> Configuration:
        if keys is None:
            keys = self.internal_keys
            if skip_last and self.name_last_pos is not None:
                keys = keys[:-1]  # Skip last pos
        return dict(zip(keys, config_tpl))