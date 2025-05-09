# This file is part of sbi, a toolkit for simulation-based inference. sbi is licensed
# under the Apache License Version 2.0, see <https://www.apache.org/licenses/>

"""Various PyTorch utility functions."""

import os
from typing import Any, Optional, Union

import numpy as np
import torch
from torch import Tensor, float32
from torch.distributions import Independent, Uniform

from sbi.sbi_types import Array, OneOrMore
from sbi.utils.typechecks import is_nonnegative_int, is_positive_int


def process_device(device: Union[str, torch.device]) -> str:
    """Set and return the default device to cpu or gpu (cuda, mps).

    Args:
        device: target torch device
    Returns:
        device: processed string, e.g., "cuda" is mapped to "cuda:0".
    """

    if device == "cpu":
        return "cpu"
    else:
        # If user just passes 'gpu', search for CUDA or MPS.
        if device == "gpu":
            # check whether either pytorch cuda or mps is available
            if torch.cuda.is_available():
                current_gpu_index = torch.cuda.current_device()
                device = f"cuda:{current_gpu_index}"
                check_device(device)
                torch.cuda.set_device(device)
            elif torch.backends.mps.is_available():
                device = "mps:0"
                # MPS support is not implemented for a number of operations.
                # use CPU as fallback.
                os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
                # MPS framework does not support double precision.
                torch.set_default_dtype(torch.float32)
                check_device(device)
            else:
                raise RuntimeError(
                    "Neither CUDA nor MPS is available. "
                    "Please make sure to install a version of PyTorch that supports "
                    "CUDA or MPS."
                )
        # Else, check whether the custom device is valid.
        else:
            check_device(device)
            if isinstance(device, torch.device):
                device = device.type

        return device


def gpu_available() -> bool:
    """Check whether GPU is available."""
    return torch.cuda.is_available() or torch.backends.mps.is_available()


def check_device(device: Union[str, torch.device]) -> None:
    """Check whether the device is valid.

    Args:
        device: target torch device
    """
    try:
        torch.randn(1, device=device)
    except (RuntimeError, AssertionError) as exc:
        raise RuntimeError(
            f"""Could not instantiate torch.randn(1, device={device}). Make sure
             the device is set up properly and that you are passing the
             corresponding device string. It should be something like 'cuda',
             'cuda:0', or 'mps'. Error message: {exc}."""
        ) from exc


def check_if_prior_on_device(
    device: Union[str, torch.device], prior: Optional[Any] = None
) -> None:
    """Try to sample from the prior, and check that the returned data is on the correct
    trainin device. If the prior is `None`, simplys pass.

    Args:
        device: target torch training device
        prior: any simulator outputing torch `Tensor`
    """
    if prior is None:
        pass
    else:
        prior_device = prior.sample((1,)).device
        training_device = torch.zeros(1, device=device).device
        assert prior_device == training_device, (
            f"Prior device '{prior_device}' must match training device "
            f"'{training_device}'. When training on GPU make sure to "
            "pass a prior initialized on the GPU as well, e.g., "
            "prior = torch.distributions.Normal"
            "(torch.zeros(2, device='cuda'), scale=1.0)`."
        )


def tile(x, n):
    if not is_positive_int(n):
        raise TypeError("Argument `n` must be a positive integer.")
    x_ = x.reshape(-1)
    x_ = x_.repeat(n)
    x_ = x_.reshape(n, -1)
    x_ = x_.transpose(1, 0)
    x_ = x_.reshape(-1)
    return x_


def sum_except_batch(x, num_batch_dims=1):
    """Sums all elements of `x` except for the first `num_batch_dims` dimensions."""
    if not is_nonnegative_int(num_batch_dims):
        raise TypeError("Number of batch dimensions must be a non-negative integer.")
    reduce_dims = list(range(num_batch_dims, x.ndimension()))
    return torch.sum(x, dim=reduce_dims)


def split_leading_dim(x, shape):
    """Reshapes the leading dim of `x` to have the given shape."""
    new_shape = torch.Size(shape) + x.shape[1:]
    return torch.reshape(x, new_shape)


def merge_leading_dims(x, num_dims):
    """Reshapes the tensor `x` such that the first `num_dims` dimensions are merged to
    one."""
    if not is_positive_int(num_dims):
        raise TypeError("Number of leading dims must be a positive integer.")
    if num_dims > x.dim():
        raise ValueError(
            "Number of leading dims can't be greater than total number of dims."
        )
    new_shape = torch.Size([-1]) + x.shape[num_dims:]
    return torch.reshape(x, new_shape)


def repeat_rows(x, num_reps):
    """Each row of tensor `x` is repeated `num_reps` times along leading dimension."""
    if not is_positive_int(num_reps):
        raise TypeError("Number of repetitions must be a positive integer.")
    shape = x.shape
    x = x.unsqueeze(1)
    x = x.expand(shape[0], num_reps, *shape[1:])
    return merge_leading_dims(x, num_dims=2)


def tensor2numpy(x):
    return x.detach().cpu().numpy()


def logabsdet(x):
    """Returns the log absolute determinant of square matrix x."""
    # Note: torch.logdet() only works for positive determinant.
    _, res = torch.slogdet(x)
    return res


def random_orthogonal(size):
    """
    Returns a random orthogonal matrix as a 2-dim tensor of shape [size, size].
    """

    # Use the QR decomposition of a random Gaussian matrix.
    x = torch.randn(size, size)
    q, _ = torch.linalg.qr(x)
    return q


def get_num_parameters(model):
    """
    Returns the number of trainable parameters in a model of type nets.Module
    :param model: nets.Module containing trainable parameters
    :return: number of trainable parameters in model
    """
    num_parameters = 0
    for parameter in model.parameters():
        num_parameters += torch.numel(parameter)
    return num_parameters


def create_alternating_binary_mask(features, even=True):
    """
    Creates a binary mask of a given dimension which alternates its masking.

    :param features: Dimension of mask.
    :param even: If True, even values are assigned 1s, odd 0s. If False, vice versa.
    :return: Alternating binary mask of type torch.Tensor.
    """
    mask = torch.zeros(features).byte()
    start = 0 if even else 1
    mask[start::2] += 1
    return mask


def create_mid_split_binary_mask(features):
    """
    Creates a binary mask of a given dimension which splits its masking at the midpoint.

    :param features: Dimension of mask.
    :return: Binary mask split at midpoint of type torch.Tensor
    """
    mask = torch.zeros(features).byte()
    midpoint = features // 2 if features % 2 == 0 else features // 2 + 1
    mask[:midpoint] += 1
    return mask


def create_random_binary_mask(features):
    """
    Creates a random binary mask of a given dimension with half of its entries
    randomly set to 1s.

    :param features: Dimension of mask.
    :return: Binary mask with half of its entries set to 1s, of type torch.Tensor.
    """
    mask = torch.zeros(features).byte()
    weights = torch.ones(features).float()
    num_samples = features // 2 if features % 2 == 0 else features // 2 + 1
    indices = torch.multinomial(
        input=weights, num_samples=num_samples, replacement=False
    )
    mask[indices] += 1
    return mask


def searchsorted(bin_locations, inputs, eps=1e-6):
    bin_locations[..., -1] += eps
    return torch.sum(inputs[..., None] >= bin_locations, dim=-1) - 1


def cbrt(x):
    """Cube root. Equivalent to torch.pow(x, 1/3), but numerically stable."""
    return torch.sign(x) * torch.exp(torch.log(torch.abs(x)) / 3.0)


def get_temperature(max_value, bound=1 - 1e-3):
    """
    For a dataset with max value 'max_value', returns the temperature such that

        sigmoid(temperature * max_value) = bound.

    If temperature is greater than 1, returns 1.

    :param max_value:
    :param bound:
    :return:
    """
    max_value = torch.Tensor([max_value])
    bound = torch.Tensor([bound])
    temperature = torch.min(
        -(1 / max_value) * (torch.log1p(-bound) - torch.log(bound)), 1
    )
    return temperature


def gaussian_kde_log_eval(samples, query):
    N, D = samples.shape[0], samples.shape[-1]
    std = N ** (-1 / (D + 4))
    precision = (1 / (std**2)) * torch.eye(D)
    a = query - samples
    b = a @ precision
    c = -0.5 * torch.sum(a * b, dim=-1)
    d = -np.log(N) - (D / 2) * np.log(2 * np.pi) - D * np.log(std)
    c += d
    return torch.logsumexp(c, dim=-1)


class BoxUniform(Independent):
    """Uniform distribution in multiple dimensions."""

    def __init__(
        self,
        low: Union[Tensor, Array],
        high: Union[Tensor, Array],
        reinterpreted_batch_ndims: int = 1,
        device: Optional[str] = None,
    ):
        """Multidimensional uniform distribution defined on a box.

        A :class:`~torch.distributions.uniform.Uniform` distribution initialized \
        with e.g. a parameter vector low or high of length 3 will result \
        in a *batch* dimension of length 3. A log_prob evaluation will then \
        output three numbers, one for each of the independent Uniforms in the \
        batch. Instead, a :class:`BoxUniform` initialized in the same way has three \
        *event* dimensions, and returns a scalar log_prob corresponding to whether \
        the evaluated point is in the box defined by low and high or outside.

        Refer to :class:`~torch.distributions.uniform.Uniform`\
        and :class:`~torch.distributions.independent.Independent` for \
        further documentation.

        Args:
            low: lower range (inclusive).
            high: upper range (exclusive).
            reinterpreted_batch_ndims (int): the number of batch dims to \
            reinterpret as event dims.
            device (Optional): device of the prior, inferred from low arg, \
            defaults to "cpu", should match the training device when used in SBI.

        Example:
        --------

        ::

            import torch
            from sbi.utils.torchutils import BoxUniform

            # Define lower bounds
            low = torch.tensor([0.0, 0.0, 0.0])

            # Define upper bounds
            high = torch.tensor([1.0, 1.0, 1.0])

            box_uniform = BoxUniform(low, high)

            # Sample from the box_uniform
            N_samples = 100
            sample = box_uniform.sample((N_samples,))

            # Evaluate the log probability of the sample
            log_prob = box_uniform.log_prob(sample)
        """

        # Type checks.
        assert isinstance(low, Tensor) and isinstance(high, Tensor), (
            f"low and high must be tensors but are {type(low)} and {type(high)}."
        )
        if not low.device == high.device:
            raise RuntimeError(
                "Expected all tensors to be on the same device, but found at least"
                f"two devices, {low.device} and {high.device}."
            )

        # Device handling
        device = low.device.type if device is None else device
        device = process_device(device)
        self.device = device
        self.reinterpreted_batch_ndims = reinterpreted_batch_ndims

        self.low = torch.as_tensor(low, dtype=torch.float32, device=device)
        self.high = torch.as_tensor(high, dtype=torch.float32, device=device)

        super().__init__(
            Uniform(
                low=torch.as_tensor(
                    low, dtype=torch.float32, device=torch.device(device)
                ),
                high=torch.as_tensor(
                    high, dtype=torch.float32, device=torch.device(device)
                ),
                validate_args=False,
            ),
            reinterpreted_batch_ndims,
        )

    def to(self, device: Union[str, torch.device]) -> None:
        """
        Moves the distribution to the specified device **in place**.

        Args:
            device: Target device (e.g., "cpu", "cuda", "mps").

        Example:
        --------

        ::

            device = "cuda"
            prior = BoxUniform(low=torch.zeros(2), high=torch.ones(2))
            prior.to(device) #inplace
        """
        # Update the device attribute
        self.device = device
        device = process_device(device)

        # Move tensors to the new device
        self.low = self.low.to(device=device)
        self.high = self.high.to(device=device)

        super().__init__(
            Uniform(
                low=self.low,
                high=self.high,
                validate_args=False,
            ),
            self.reinterpreted_batch_ndims,
        )


def ensure_theta_batched(theta: Tensor) -> Tensor:
    r"""
    Return parameter set theta that has a batch dimension, i.e. has shape
     (1, shape_of_single_theta)

     Args:
         theta: parameters $\theta$, of shape (n) or (1,n)
     Returns:
         Batched parameter set $\theta$
    """

    # => ensure theta has shape (1, dim_parameter)
    if theta.ndim == 1:
        theta = theta.unsqueeze(0)

    return theta


def ensure_x_batched(x: Tensor) -> Tensor:
    """
    Return simulation output x that has a batch dimension, i.e. has shape
    (1, shape_of_single_x).

    Args:
         x: simulation output of shape (n) or (1,n).
     Returns:
         Batched simulation output x.
    """

    # ensure x has shape (1, shape_of_single_x). If shape[0] > 1, we assume that
    # the batch-dimension is missing, even though ndim might be >1 (e.g. for images)
    if x.shape[0] > 1 or x.ndim == 1:
        x = x.unsqueeze(0)

    return x


def atleast_2d_many(*arys: Array) -> OneOrMore[Tensor]:
    """Return tensors with at least dimension 2.

    Tensors or arrays of dimension 0 or 1 will get additional dimension(s) prepended.

    Returns:
        Tensor or list of tensors all with dimension >= 2.
    """
    if len(arys) == 1:
        arr = arys[0]
        if isinstance(arr, np.ndarray):
            arr = torch.from_numpy(arr)
        return atleast_2d(arr)
    else:
        return [atleast_2d_many(arr) for arr in arys]  # type: ignore


def atleast_2d(t: Tensor) -> Tensor:
    return t if t.ndim >= 2 else t.reshape(1, -1)


def maybe_add_batch_dim_to_size(s: torch.Size) -> torch.Size:
    """
    Take a torch.Size and add a batch dimension to it if dimensionality of size is 1.

    (N) -> (1,N)
    (1,N) -> (1,N)
    (N,M) -> (N,M)
    (1,N,M) -> (1,N,M)

    Args:
        s: Input size, possibly without batch dimension.

    Returns: Batch size.

    """
    return s if len(s) >= 2 else torch.Size([1]) + s  # type: ignore


def atleast_2d_float32_tensor(arr: Union[Tensor, np.ndarray]) -> Tensor:
    return atleast_2d(torch.as_tensor(arr, dtype=float32))


def batched_first_of_batch(t: Tensor) -> Tensor:
    """
    Takes in a tensor of shape (N, M) and outputs tensor of shape (1,M).
    """
    return t[:1]


def assert_all_finite(quantity: Tensor, description: str = "tensor") -> None:
    """Raise if tensor quantity contains any NaN or Inf element."""

    msg = f"NaN/Inf present in {description}."
    assert torch.isfinite(quantity).all(), msg


def assert_not_nan_or_plus_inf(quantity: Tensor, description: str = "tensor") -> None:
    """Raise if tensor quantity contains any NaN or +Inf element."""

    msg = f"NaN/ +Inf present in {description}."
    assert not (torch.isposinf(quantity).any()) and not (torch.isnan(quantity).any()), (
        msg
    )
