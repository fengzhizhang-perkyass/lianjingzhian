"""Label-free neighbor dispersion and standardized directional deviation."""
import numpy as np


def neighborhood_statistics(x, operators, std_floor=.5, clip=8):
    if std_floor <= 0 or clip <= 0:
        raise ValueError('Neighborhood scale parameters must be positive')
    x = np.asarray(x, dtype=np.float32)
    for direction in ('out', 'in'):
        operator = operators[direction]
        mean = np.asarray(operator @ x, dtype=np.float32)
        second_moment = np.asarray(operator @ np.square(x), dtype=np.float32)
        std = np.sqrt(np.maximum(second_moment-np.square(mean), 0))
        zscore = np.clip((x-mean)/np.maximum(std, std_floor), -clip, clip)
        # No neighbors means no relative evidence, rather than a synthetic deviation.
        isolated = np.asarray(operator.sum(axis=1)).ravel() == 0
        zscore[isolated] = 0
        yield direction+'_std', std
        yield direction+'_zscore', zscore
