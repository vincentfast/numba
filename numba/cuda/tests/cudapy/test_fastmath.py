from typing import List
from dataclasses import dataclass, field
from numba import cuda, float32
from numba.cuda.compiler import compile_ptx_for_current_device
from math import cos, sin, tan, exp, log, log10, log2, pow
from operator import truediv
import numpy as np
from numba.cuda.testing import CUDATestCase, skip_on_cudasim
import unittest


@dataclass
class FastMathCriterion:
    fast_expected: List[str] = field(default_factory=list)
    fast_unexpected: List[str] = field(default_factory=list)
    slow_expected: List[str] = field(default_factory=list)
    slow_unexpected: List[str] = field(default_factory=list)

    def check(self, test: CUDATestCase, fast: str, slow: str):
        test.assertTrue(all(i in fast for i in self.fast_expected))
        test.assertTrue(all(i not in fast for i in self.fast_unexpected))
        test.assertTrue(all(i in slow for i in self.slow_expected))
        test.assertTrue(all(i not in slow for i in self.slow_unexpected))


@skip_on_cudasim('Fastmath and PTX inspection not available on cudasim')
class TestFastMathOption(CUDATestCase):
    def _test_fast_math_common(self, pyfunc, sig, device, criterion):

        # Test jit code path
        # For device function, the advised way to retrieve ptx is through
        # compile_ptx_*. See:
        # https://numba.readthedocs.io/en/stable/reference/deprecation.html#deprecation-of-the-inspect-ptx-method # noqa E501
        if not device:
            fastver = cuda.jit(sig, device=device, fastmath=True)(pyfunc)
            slowver = cuda.jit(sig, device=device)(pyfunc)
            criterion.check(self, fastver.ptx[sig], slowver.ptx[sig])

        # Test compile_ptx code path
        fastptx, _ = compile_ptx_for_current_device(
            pyfunc, sig, device=device, fastmath=True
        )
        slowptx, _ = compile_ptx_for_current_device(
            pyfunc, sig, device=device
        )
        criterion.check(self, fastptx, slowptx)

    def _test_fast_math_unary(self, op, criterion: FastMathCriterion):
        def kernel(r, x):
            r[0] = op(x)

        def device(x):
            return op(x)

        self._test_fast_math_common(
            kernel, (float32[::1], float32), device=False, criterion=criterion
        )
        self._test_fast_math_common(
            device, (float32,), device=True, criterion=criterion
        )

    def _test_fast_math_binary(self, op, criterion: FastMathCriterion):
        def kernel(r, x, y):
            r[0] = op(x, y)

        def device(x, y):
            return op(x, y)

        self._test_fast_math_common(
            kernel,
            (float32[::1], float32, float32), device=False, criterion=criterion
        )
        self._test_fast_math_common(
            device, (float32, float32), device=True, criterion=criterion
        )

    def test_cosf(self):
        self._test_fast_math_unary(
            cos,
            FastMathCriterion(
                fast_expected=['cos.approx.ftz.f32 '],
                slow_unexpected=['cos.approx.ftz.f32 ']
            )
        )

    def test_sinf(self):
        self._test_fast_math_unary(
            sin,
            FastMathCriterion(
                fast_expected=['sin.approx.ftz.f32 '],
                slow_unexpected=['sin.approx.ftz.f32 ']
            )
        )

    def test_tanf(self):
        self._test_fast_math_unary(
            tan,
            FastMathCriterion(fast_expected=[
                'sin.approx.ftz.f32 ',
                'cos.approx.ftz.f32 ',
                'div.approx.ftz.f32 '
            ], slow_unexpected=['sin.approx.ftz.f32 '])
        )

    def test_expf(self):
        self._test_fast_math_unary(
            exp,
            FastMathCriterion(
                fast_unexpected=['fma.rn.f32 '],
                slow_expected=['fma.rn.f32 ']
            )
        )

    def test_logf(self):
        # Look for constant used to convert from log base 2 to log base e
        self._test_fast_math_unary(
            log, FastMathCriterion(
                fast_expected=['lg2.approx.ftz.f32 ', '0f3F317218'],
                slow_unexpected=['lg2.approx.ftz.f32 '],
            )
        )

    def test_log10f(self):
        # Look for constant used to convert from log base 2 to log base 10
        self._test_fast_math_unary(
            log10, FastMathCriterion(
                fast_expected=['lg2.approx.ftz.f32 ', '0f3E9A209B'],
                slow_unexpected=['lg2.approx.ftz.f32 ']
            )
        )

    def test_log2f(self):
        self._test_fast_math_unary(
            log2, FastMathCriterion(
                fast_expected=['lg2.approx.ftz.f32 '],
                slow_unexpected=['lg2.approx.ftz.f32 ']
            )
        )

    def test_powf(self):
        self._test_fast_math_binary(
            pow, FastMathCriterion(
                fast_expected=['lg2.approx.ftz.f32 '],
                slow_unexpected=['lg2.approx.ftz.f32 '],
            )
        )

    def test_divf(self):
        self._test_fast_math_binary(
            truediv, FastMathCriterion(
                fast_expected=['div.approx.ftz.f32 '],
                fast_unexpected=['div.rn.f32'],
                slow_expected=['div.rn.f32'],
                slow_unexpected=['div.approx.ftz.f32 '],
            )
        )

    def test_divf_exception(self):
        def f10(r, x, y):
            r[0] = x / y

        sig = (float32[::1], float32, float32)
        fastver = cuda.jit(sig, fastmath=True, debug=True)(f10)
        slowver = cuda.jit(sig, debug=True)(f10)
        nelem = 10
        ary = np.empty(nelem, dtype=np.float32)
        with self.assertRaises(ZeroDivisionError):
            slowver[1, nelem](ary, 10.0, 0.0)

        try:
            fastver[1, nelem](ary, 10.0, 0.0)
        except ZeroDivisionError:
            self.fail("Divide in fastmath should not throw ZeroDivisionError")


if __name__ == '__main__':
    unittest.main()
