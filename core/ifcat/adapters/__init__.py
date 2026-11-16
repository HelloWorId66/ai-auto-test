from .base import Adapter  # noqa: F401
from .registry import AdapterRegistry, RegistryError  # noqa: F401
from .business import (
    AccountOpenOrganAdapter,
    AmountCompAdapter,
    CountryAreaAdapter,
    CurrencyAdapter,
    InterestRateAdapter,
    PaymentAccountAdapter,
    PaymentUnitAdapter,
)
from .generic import (
    ComboBoxAdapter,
    DateAdapter,
    HelpComboBoxAdapter,
    NumberInputAdapter,
    TextAreaAdapter,
    TextInputAdapter,
)

_CORE = [
    TextInputAdapter,
    TextAreaAdapter,
    NumberInputAdapter,
    DateAdapter,
    ComboBoxAdapter,
    HelpComboBoxAdapter,
    PaymentUnitAdapter,
    AccountOpenOrganAdapter,
    PaymentAccountAdapter,
    CountryAreaAdapter,
    CurrencyAdapter,
    InterestRateAdapter,
    AmountCompAdapter,
]


def build_default_registry() -> AdapterRegistry:
    reg = AdapterRegistry()
    for cls in _CORE:
        reg.register_core(cls)
    reg.lock_core()
    return reg
