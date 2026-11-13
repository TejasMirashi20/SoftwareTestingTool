"""Bank account management with validation and custom exceptions."""
from datetime import datetime


class InsufficientFundsError(Exception):
    """Raised when a withdrawal or transfer exceeds the available balance."""


def format_currency(amount: float) -> str:
    """Format a number as a currency string."""
    return f"${amount:,.2f}"


class BankAccount:
    """A simple bank account that records every transaction."""

    def __init__(self, owner: str, balance: float):
        if balance < 0:
            raise ValueError("opening balance cannot be negative")
        self.owner = owner
        self.balance = balance
        self.history = []

    def _record(self, kind: str, amount: float) -> None:
        """Append a transaction to the history."""
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.history.append((stamp, kind, amount))

    def deposit(self, amount: float) -> float:
        """Add money to the account and return the new balance."""
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self.balance += amount
        self._record("deposit", amount)
        return self.balance

    def withdraw(self, amount: float) -> float:
        """Remove money from the account and return the new balance."""
        if amount <= 0:
            raise ValueError("withdrawal must be positive")
        if amount > self.balance:
            raise InsufficientFundsError("not enough funds")
        self.balance -= amount
        self._record("withdrawal", amount)
        return self.balance

    def transfer(self, target: "BankAccount", amount: float) -> None:
        """Move money to another account."""
        self.withdraw(amount)
        target.deposit(amount)

    def apply_interest(self, rate: float) -> float:
        """Add interest (rate is a percentage) and return the interest earned."""
        if rate < 0:
            raise ValueError("interest rate cannot be negative")
        interest = self.balance * rate / 100
        self.balance += interest
        self._record("interest", interest)
        return interest

    def statement(self) -> str:
        """Return a printable statement."""
        lines = [f"Statement for {self.owner}"]
        for stamp, kind, amount in self.history:
            lines.append(f"{stamp}  {kind:<10} {format_currency(amount)}")
        lines.append(f"Balance: {format_currency(self.balance)}")
        return "\n".join(lines)


def main() -> None:
    """Demonstrate deposits, withdrawals and a transfer."""
    alice = BankAccount("Alice", 500.0)
    bob = BankAccount("Bob", 100.0)
    alice.deposit(250)
    alice.transfer(bob, 300)
    try:
        bob.withdraw(10_000)
    except InsufficientFundsError as error:
        print("Rejected:", error)
    alice.apply_interest(2.5)
    print(alice.statement())
    print(bob.statement())


if __name__ == "__main__":
    main()
