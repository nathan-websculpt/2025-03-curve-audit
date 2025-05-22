# https://codehawks.cyfrin.io/c/2025-03-curve/s/cm86w92zx000bl403jn102c7n
# asymetric time constraints allow larger upside movement, invalidating security measure

import pytest
import rlp
import boa

from scripts.scrvusd.proof import serialize_proofs
from tests.conftest import WEEK
from tests.scrvusd.verifier.conftest import MAX_BPS_EXTENDED
from tests.shared.verifier import get_block_and_proofs


@pytest.fixture(scope="module")
def scrvusd_slot_values(scrvusd, crvusd, admin, anne):
    deposit = 10**18
    with boa.env.prank(anne):
        crvusd._mint_for_testing(anne, deposit)
        crvusd.approve(scrvusd, deposit)
        scrvusd.deposit(deposit, anne)
        # New scrvusd parameters:
        #   scrvusd.total_idle = deposit,
        #   scrvusd.total_supply = deposit.

    rewards = 10**17
    with boa.env.prank(admin):
        crvusd._mint_for_testing(scrvusd, rewards)
        scrvusd.process_report(scrvusd)
        # Minted `rewards` shares to scrvusd, because price is still == 1.

    # Record the initial values
    last_profit_update = boa.env.evm.patch.timestamp

    # Travel forward in time to create a significant gap between current timestamp and last_profit_update
    boa.env.time_travel(seconds=3*86400, block_delta=3*12)  # 3 days forward

    return {
        "total_debt": 0,
        "total_idle": deposit + rewards,
        "total_supply": deposit + rewards,
        "full_profit_unlock_date": last_profit_update + WEEK,
        "profit_unlocking_rate": rewards * MAX_BPS_EXTENDED // WEEK,
        "last_profit_update": last_profit_update,
        "balance_of_self": rewards,
    }


def test_using_last_profit_update_as_timestamp_surrogate_is_broken(
    verifier, soracle_price_slots, soracle, boracle, scrvusd, scrvusd_slot_values
):
    """
    Test demonstrates how using last_profit_update as a timestamp surrogate in verifyScrvusdByStateRoot
    leads to divergent price calculations compared to verifyScrvusdByBlockHash which uses current timestamp.

    """
    # Get current and previous timestamps for analysis
    current_timestamp = boa.env.evm.patch.timestamp
    last_profit_update = scrvusd_slot_values["last_profit_update"]

    # CASE 1: Using verifyScrvusdByBlockHash (which uses current timestamp)
    # --------------------------------------------------------------------------

    block_header, proofs = get_block_and_proofs([(scrvusd, soracle_price_slots)])
    boracle._set_block_hash(block_header.block_number, block_header.hash)

    # Execute verification using blockHash method
    tx1 = verifier.verifyScrvusdByBlockHash(
        rlp.encode(block_header),
        serialize_proofs(proofs[0]),
    )

    # Record the timestamp used after blockHash verification
    blockhash_timestamp = soracle._storage.price_params_ts.get()

    # Save the value after blockHash call to compare later
    blockhash_block_number = soracle.last_block_number

    # CASE 2: Using verifyScrvusdByStateRoot (which uses last_profit_update as timestamp)
    # -----------------------------------------------------------------------------------

    # Set up new state root verification
    block_header, proofs = get_block_and_proofs([(scrvusd, soracle_price_slots)])
    boracle._set_state_root(block_header.block_number, block_header.state_root)

    # Execute verification using stateRoot method
    tx2 = verifier.verifyScrvusdByStateRoot(
        block_header.block_number,
        serialize_proofs(proofs[0]),
    )

    # Record the timestamp used after stateRoot verification
    stateroot_timestamp = soracle._storage.price_params_ts.get()

    # ANALYSIS: Compare the results
    # ------------------------------------

    # Verify the timestamps used are different
    assert blockhash_timestamp != stateroot_timestamp, "Timestamps should be different between methods"

    # Calculate periods that would be applied in each method
    daily_period = 86400  # 1 day in seconds
    periods_blockHash = (blockhash_timestamp - last_profit_update) // daily_period
    periods_stateRoot = (stateroot_timestamp - last_profit_update) // daily_period

    print(f"\nProfit evolution periods with blockHash method: {periods_blockHash}")
    print(f"Profit evolution periods with stateRoot method: {periods_stateRoot}")

    assert abs(stateroot_timestamp - last_profit_update) == 0, "StateRoot should use last_profit_update as timestamp"
    assert blockhash_timestamp != stateroot_timestamp, "Timestamps should differ between methods"

    # Show impact on profit evolution since periods would be zero when verification is done with stateRoot
    assert periods_blockHash != 0
    assert periods_stateRoot == 0
