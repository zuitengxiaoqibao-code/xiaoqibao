import re


CONVERTIBLE_BOND_CODE = re.compile(r"^(?:110|111|113|118|123|127|128)\d{3}$")
A_SHARE_CODE = re.compile(r"^[036]\d{5}$")


def validate_convertible_bond_code(value: str) -> str:
    if not CONVERTIBLE_BOND_CODE.fullmatch(value):
        raise ValueError("bond code must be a supported six-digit convertible bond code")
    return value


def validate_a_share_code(value: str) -> str:
    if not A_SHARE_CODE.fullmatch(value):
        raise ValueError("stock code must be a supported six-digit A-share code")
    return value
