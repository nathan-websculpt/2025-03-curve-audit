import pytest
import boa

from tests.scrvusd.conftest import DEFAULT_MAX_PRICE_INCREMENT, DEFAULT_MAX_V2_DURATION


@pytest.fixture(scope="module")
def soracle(admin):
    with boa.env.prank(admin):
        contract = boa.load("contracts/scrvusd/oracles/ScrvusdOracleV2.vy", 10**18)
    return contract


def test_ownership(soracle, admin, anne):
    admin_role = soracle.DEFAULT_ADMIN_ROLE()

    assert soracle.hasRole(admin_role, admin)

    # Reachable for admin
    with boa.env.prank(admin):
        soracle.set_max_price_increment(DEFAULT_MAX_PRICE_INCREMENT + 1)
        soracle.set_max_v2_duration(DEFAULT_MAX_V2_DURATION + 1)

    # Not reachable for third party
    with boa.env.prank(anne):
        with boa.reverts():
            soracle.set_max_price_increment(DEFAULT_MAX_PRICE_INCREMENT + 2)
        with boa.reverts():
            soracle.set_max_v2_duration(DEFAULT_MAX_V2_DURATION + 2)

    # Transferable
    with boa.env.prank(admin):
        soracle.grantRole(admin_role, anne)
        soracle.revokeRole(admin_role, admin)
    assert soracle.hasRole(admin_role, anne)
    assert not soracle.hasRole(admin_role, admin)

    # Reachable for new owner
    with boa.env.prank(anne):
        soracle.set_max_price_increment(DEFAULT_MAX_PRICE_INCREMENT + 2)
        soracle.set_max_v2_duration(DEFAULT_MAX_V2_DURATION + 2)

    # Renounceable, making it immutable
    with boa.env.prank(anne):
        soracle.revokeRole(admin_role, anne)
        with boa.reverts():
            soracle.set_max_price_increment(DEFAULT_MAX_PRICE_INCREMENT + 1)
        with boa.reverts():
            soracle.set_max_v2_duration(DEFAULT_MAX_V2_DURATION + 1)

@pytest.fixture(scope="module")
def soracle(admin):
    with boa.env.prank(admin):
        # assume we are deploying the oracle for the new blockchain after years of scrvUSD existence,
        # so the price reached 4 crvUSD per scrvUSD, _initial_price is 4*10**18
        contract = boa.load("contracts/scrvusd/oracles/ScrvusdOracleV2.vy", 4*10**18)
    return contract

# https://codehawks.cyfrin.io/c/2025-03-curve/s/cm8907inc0005l503zgtbu3ob
def test_initial_price_at_later_oracle_deploy(soracle, verifier, admin):
    print("\n| where                      | price_v2()        | raw_price()       | block_number")
    # here price_v2() returns 4, but raw_price() returns 1
    price_v2, raw_price = soracle.price_v2(), soracle.raw_price()
    print("  on init                    ", price_v2, raw_price, boa.env.evm.patch.block_number)
    assert price_v2 == 4*10**18
    assert raw_price == 1*10**18  # incorrect

    # assume for some reason we want to increase the max_price_increment
    with boa.env.prank(admin):
        soracle.set_max_price_increment(10**18)
    
    # then if we do not update the price at the same block, the price at price_v2() will be inconsistent and equal to 1
    boa.env.time_travel(seconds=12)
    price_v2, raw_price = soracle.price_v2(), soracle.raw_price()
    print("  max_price_increment updated", price_v2, raw_price, boa.env.evm.patch.block_number)
    assert price_v2 == 1*10**18   # incorrect
    assert raw_price == 1*10**18  # incorrect

    # prepare the price parameters
    ts = boa.env.evm.patch.timestamp
    price_params = [
        0,                                # total_debt
        40000000000000000000000000,       # total_idle
        10000000000000000000000000,       # totalSupply
        ts + 500000,                      # full_profit_unlock_date
        5831137848451547566180476730,     # profit_unlocking_rate
        ts,                               # last_profit_update
        3000000000000000000000,           # balanceOf(self)
    ]

    with boa.env.prank(verifier):
        soracle.update_price(
            price_params,
            ts,
            boa.env.evm.patch.block_number,
        )

    # only after price update the raw_price() will be consistent and equal to 4
    # but price_v2() will still be inconsistent and equal to 1
    price_v2, raw_price = soracle.price_v2(), soracle.raw_price()
    print("  after update_price         ", price_v2, raw_price, boa.env.evm.patch.block_number)
    assert price_v2 == 1*10**18  # incorrect
    assert raw_price == 4*10**18

    # only at the next block the price_v2() will become consistent
    boa.env.time_travel(seconds=12)
    price_v2, raw_price = soracle.price_v2(), soracle.raw_price()
    print("  wait one block             ", price_v2, raw_price, boa.env.evm.patch.block_number)
    assert price_v2 > 4*10**18
    assert raw_price > 4*10**18

# run it with `-s` flag to see the print statements
# pytest tests/scrvusd/oracle/unitary/test_v2.py::test_initial_price_at_later_oracle_deploy -s

# stdout output:
#| where                      | price_v2()        | raw_price()       | block_number
#  on init                     4000000000000000000 1000000000000000000 1
#  max_price_increment updated 1000000000000000000 1000000000000000000 2
#  after update_price          1000000000000000000 4000000000000000000 2
#  wait one block              4000000027989461868 4000000027989461868 3



def test_setters(soracle, admin):
    with boa.env.prank(admin):
        soracle.set_max_price_increment(DEFAULT_MAX_PRICE_INCREMENT + 1)
        assert soracle.max_price_increment() == DEFAULT_MAX_PRICE_INCREMENT + 1

        soracle.set_max_v2_duration(DEFAULT_MAX_V2_DURATION + 1)
        assert soracle.max_v2_duration() == DEFAULT_MAX_V2_DURATION + 1


def test_update_profit_max_unlock_time(soracle, verifier, anne):
    # Not available to a third party
    with boa.env.prank(anne):
        with boa.reverts():
            soracle.update_profit_max_unlock_time(
                8 * 86400,  # new value
                10,  # block number
            )

    with boa.env.prank(verifier):
        soracle.update_profit_max_unlock_time(
            8 * 86400,  # new value
            10,  # block number
        )
        assert soracle.last_block_number() == 10

        # Linearizability by block number
        with boa.reverts():
            soracle.update_profit_max_unlock_time(
                8 * 86400,  # new value
                8,  # block number
            )

        # "Breaking" resubmit at same block
        soracle.update_profit_max_unlock_time(
            6 * 86400,  # new value
            10,  # block number
        )


def test_update_price(soracle, verifier, anne):
    ts = boa.env.evm.patch.timestamp
    price_1_5_parameters = [3, 0, 2, ts + 7 * 86400, 0, 0, 0]
    price_0_5_parameters = [2, 0, 3, ts + 7 * 86400, 0, 0, 0]

    # Not available to a third party
    with boa.env.prank(anne):
        with boa.reverts():
            soracle.update_price(
                price_1_5_parameters,
                ts + 100,  # timestamp
                10,  # block number
            )

    with boa.env.prank(verifier):
        soracle.update_price(
            price_1_5_parameters,
            ts + 100,  # timestamp
            10,  # block number
        )
        assert soracle.last_block_number() == 10

        # Linearizability by block number
        with boa.reverts():
            soracle.update_price(
                price_1_5_parameters,
                ts + 101,  # timestamp
                8,  # block number
            )

        # "Breaking" resubmit at same block
        soracle.update_price(
            price_0_5_parameters,
            ts + 99,  # timestamp
            10,  # block number
        )
