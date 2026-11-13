"""Scientific calculator: clean, modular and defensive (expected: LOW risk)."""
import math


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return a divided by b; raise ValueError when b is zero."""
    if b == 0:
        raise ValueError("division by zero is undefined")
    return a / b


def power(base: float, exponent: float) -> float:
    """Return base raised to exponent; raise ValueError if the result overflows."""
    try:
        return base**exponent
    except OverflowError as exc:
        raise ValueError("result is too large") from exc


def square_root(value: float) -> float:
    """Return the square root of a non-negative number."""
    if value < 0:
        raise ValueError("square root of a negative number is undefined")
    return math.sqrt(value)


def factorial(number: int) -> int:
    """Return number! for 0 <= number <= 170."""
    if number < 0:
        raise ValueError("factorial is undefined for negative numbers")
    if number > 170:
        raise ValueError("number is too large")
    return math.factorial(number)


def logarithm(value: float, base: float = 10.0) -> float:
    """Return the logarithm of value in the given base."""
    if value <= 0:
        raise ValueError("logarithm needs a positive value")
    if base <= 0 or base == 1:
        raise ValueError("invalid logarithm base")
    return math.log(value, base)


def sine_degrees(angle: float) -> float:
    """Return the sine of an angle given in degrees."""
    return math.sin(math.radians(angle))


def cosine_degrees(angle: float) -> float:
    """Return the cosine of an angle given in degrees."""
    return math.cos(math.radians(angle))


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole."""
    if whole == 0:
        raise ValueError("the whole must not be zero")
    return part / whole * 100


def mean(values: list) -> float:
    """Return the arithmetic mean of a non-empty list of numbers."""
    if not values:
        raise ValueError("cannot average an empty list")
    return sum(values) / len(values)


def evaluate(operation: str, a: float, b: float) -> float:
    """Apply a named binary operation to a and b."""
    operations = {"add": add, "sub": subtract, "mul": multiply, "div": divide}
    if operation not in operations:
        raise ValueError(f"unknown operation: {operation}")
    return operations[operation](a, b)


def main() -> None:
    """Print a small demonstration of the calculator."""
    print("2 + 3 =", add(2, 3))
    print("10 / 4 =", divide(10, 4))
    print("2 ^ 8 =", power(2, 8))
    print("sqrt(81) =", square_root(81))
    print("5! =", factorial(5))
    print("log10(1000) =", logarithm(1000))
    print("sin(30) =", round(sine_degrees(30), 3))
    print("25% of 80 =", percentage(25, 80))
    print("mean =", mean([2, 4, 6]))
    print("evaluate =", evaluate("mul", 6, 7))


if __name__ == "__main__":
    main()
