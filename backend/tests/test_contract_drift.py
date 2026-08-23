from backend.scripts.check_contracts import find_contract_drift


def test_public_contract_fields_stay_aligned():
    assert find_contract_drift() == []
