# METER

Pay for the uptime you got, not the uptime you were promised.

A service sold on "99.9% uptime" is paid for in advance and argued about afterwards. The buyer pays the full fee, the provider has a bad week, and the remedy is a support ticket asking for credit. METER inverts that. The buyer escrows the fee, the contract samples the provider's own health URL across the billing window under consensus, and when the window closes the provider is paid for the share of samples that found the service up. The rest goes back to the buyer, automatically, in the same transaction.

Every sample is a live HTTP fetch of a third-party URL that neither side controls once the plan is agreed, read independently by every validator.

**This is a bill, not insurance.** [PERIL](https://github.com/Jennivarl/peril), an earlier project of mine, also watches for outages, but it is cover: a policyholder pays a premium into a pool and is paid a fixed sum if an outage happens. METER has no pool, no claim and no event. A buyer pays a provider for a service, and the amount is computed from many measurements of that service across the billing window. Any URL works, not only status pages.

| contract | what it does |
|---|---|
| **PLAN** | The terms: provider, URL, the marker a healthy response contains, the fee, the window length. Proposed by the buyer, accepted by the provider. |
| **METER** | The measurements. Each sample is one consensus round over a real fetch of the agreed URL. |
| **LEDGER** | The escrow. Divides the fee by what METER measured once the window has closed. |
| **GRADE** | The reference consumer: a renewal that only opens on a closed window that measured high enough. |

| | |
|---|---|
| Network | GenLayer Studio Next, chain id 61997, `https://studio-next.genlayer.com/api` |
| Engine | Consensus v0.6, GenVM v0.3, runner `py-genlayer:5jycge...` |
| METER | [`0xE93D3cCb49dEd2a834B3D698A868fD165dd67b67`](https://explorer-studio-dev.genlayer.com/address/0xE93D3cCb49dEd2a834B3D698A868fD165dd67b67) |
| Tests | 174, `python -m pytest -q` |

---

## Every sample counts, and only a healthy one is paid

The tempting design has three buckets: up, down, and "could not tell" for a host the validators failed to reach or a status that might be about the route rather than the service. It is wrong, and the reason is the whole design.

A bucket that does not count is a lever, and the provider is the one holding it. Suppose unreachable samples are set aside. A server that answers three good samples and then goes completely dark stands at **3 up out of 3 counted**, and is paid in full for a month it spent offline. The same goes for any status a provider can serve on purpose: return a 403 while broken, and the broken hours vanish from the denominator.

So METER has two outcomes. A response that succeeded and contains the agreed marker is **up**. Everything else is **down**, with the reason kept: answered without the marker, answered 503, answered 403, could not be reached. The provider chose the URL and agreed to be measured from it; a URL the network cannot read is a sample against them.

**This is the opposite of how [VIGIL](https://github.com/Jennivarl/Vigil) treats the same fact, deliberately.** VIGIL hands over an inheritance when a page goes silent, so mistaking an unreachable host for silence would hand over an estate: there, an unreachable host must count for nothing. Here, ignoring it would pay for an outage. Which way an ambiguous reading falls is decided by who would be hurt by getting it wrong.

### Validators agree on whether it was down, not why

A healthy response looks the same from everywhere: a 200 containing the marker. A real outage does not. One validator sees a 502, another a 503, a third a timeout, and all three are right that the service was down. An earlier version of this contract required validators to agree on the reason as well as the outcome. That made outages fail consensus far more often than healthy samples, so outage samples quietly went unrecorded while healthy ones always landed, and every bill leaned toward the provider. Nothing about the money depends on the reason, so it is no longer compared, and because consensus no longer agrees on it, it is no longer stored. Only the outcome is written down.

---

## The rules, and what each one stops

**The fee goes in before the provider accepts.** Otherwise a buyer could watch the first samples and fund only a plan that was going to cost little, leaving a provider who had been reliable unpaid. LEDGER refuses a fee once the plan is live.

**The window opens at acceptance, and lasts an hour to a month.** Nobody types a start date, so nobody can choose one that happens to miss a known outage, and nothing is measured before both sides have agreed to the terms. An hour leaves room for the minimum three samples with slack, so one slow transaction cannot leave a plan unable to bill.

**Samples are at least ten minutes apart, across every caller.** Otherwise a party could take a burst of samples in one good minute and call it a month.

**Samples only exist inside the window.** One taken after the window closes is refused, so the tally LEDGER settles on is final and nothing can be added to it once money has moved.

**Three samples or nothing.** Below that, the provider is paid nothing and the buyer gets the whole fee back. Two samples cannot tell a flaky minute from a bad month, and billing on no evidence is paying for a promise again.

**The split is exact.** The provider gets `fee × up ÷ samples`, rounded down. The buyer gets everything else. The two parts always sum to exactly the fee, checked against five thousand random tallies, so no rounding can create or lose value, and the fraction left by rounding goes to the side that paid.

---

## What consensus derived, and what was copied

| stored field | where it comes from | derived or copied |
|---|---|---|
| each sample's outcome | every validator fetched the agreed URL itself and reached the same up or down | derived |
| the URL fetched | built by the contract from the plan's host and path | derived |
| the up and down counts | the contract's own arithmetic over agreed samples | derived |
| sample timestamps, window open and close | the transactions' own `datetime` | derived |
| the provider's payment and the buyer's refund | `share()` over the final tally | derived |
| the host, path, marker, fee and window length | the buyer's proposal, accepted by the provider, immutable | theirs, immutably |

The leader's reading is used for one thing: as the proposal each validator checks against its own fetch, by exact equality on the outcome. The reason a sample was down is visible in each validator's execution on the explorer; it is not written to the contract, because consensus did not agree on it.

---

## What a dishonest leader can try

| the lie | what it would buy | what happens | test |
|---|---|---|---|
| call an outage up | pays the provider for a broken service | rejected | `test_a_validator_rejects_a_leader_who_calls_an_outage_up` |
| call a healthy service down | refunds the buyer for a service they got | rejected | `test_a_validator_rejects_a_leader_who_calls_a_healthy_service_down` |
| hide an outage by disputing its reason | an outage that never reaches the tally, if validators had to agree on why | not possible: only the outcome is compared, so a 502 and a timeout are both down | `test_validators_agree_an_outage_was_down_whatever_each_of_them_saw` |
| invent an outcome | anything outside up and down | rejected, and refused again before storage | `test_a_validator_rejects_an_outcome_the_contract_does_not_define` |
| crash instead of answering | stalls the round | rejected: a malformed result is a disagreement | `test_a_validator_rejects_a_leader_that_errored` |

---

## Every funded state has a way out

| state | the way out |
|---|---|
| funded, the provider never accepted | the buyer withdraws the plan in PLAN, then reclaims the whole fee in LEDGER |
| live, window closed, three or more samples | settle divides the fee by measured uptime |
| live, window closed, fewer than three samples | settle returns the whole fee to the buyer |

Settling and reclaiming can never both be open: one needs the plan `live`, the other needs it `withdrawn`. Reclaiming requires the buyer to withdraw first, which also stops the provider accepting afterwards, so the fee can never leave while a provider is still entitled to take the plan.

---

## Verified live on Studio Next

Two plans run side by side against **GitHub's own status API**, `https://www.githubstatus.com/api/v2/status.json`, a page nobody involved controls. The provider is a second wallet that accepted both plans itself. Every address in [`deploy/live.json`](deploy/live.json) runs the exact bundle committed here, which `deploy/verify.mjs` proves by hashing the source carried in each deploy transaction.

- **github** counts a sample up when the page contains `All Systems Operational`.
- **outage** counts a sample up only when it contains `Partial System Outage`, so it should read down whenever GitHub is not in that exact state.

The run happened to overlap a real incident. GitHub opened a **critical** incident at 15:49 UTC on 19 October 2026, *Degraded availability for GitHub Actions, GitHub Pages and Webhooks*, resolved before 16:57. The first two samples landed while it was open and read down; the last two landed after recovery and read up. Nothing was staged: a third party had a bad hour, and the bill measured it.

| step | transaction | result |
|---|---|---|
| Propose, fund, accept: github | [`0x7c0d3f9a...`](https://explorer-studio-dev.genlayer.com/tx/0x7c0d3f9a277c551e850866593e2d1ae56735cdfe682e6603646976123fbc4958) | 0.02 GEN, a one-hour window. [Funded](https://explorer-studio-dev.genlayer.com/tx/0xc0473e80c154cf0a008f788bbb2ffa0901da83fb31aeb06bf02894e559e88dec) **before** the provider [accepted](https://explorer-studio-dev.genlayer.com/tx/0xaf9b632a8eb41f1d8470572f68b5b0e04ea0a355e7d3a72f988a14e8c516c76c) from its own wallet |
| Propose, fund, accept: outage | [`0xf61bc53e...`](https://explorer-studio-dev.genlayer.com/tx/0xf61bc53e26bab6ba6cabdaf70abcd66908aafcc1d2bcaff8fcc00b5e3197cc80) | the same terms with the other marker. [Funded](https://explorer-studio-dev.genlayer.com/tx/0xc36c0f260e020850cdfb1cf2afaae391cdb2181d609fe2d66f65df109046edf6), [accepted](https://explorer-studio-dev.genlayer.com/tx/0x8c11bf8d6c65caead8b9b429bb04f72a6d4f978c5ffe48be0c10fc7a823ab22e) |
| Settle, too early | [`0xe04b65d7...`](https://explorer-studio-dev.genlayer.com/tx/0xe04b65d708cb0bf0f53c66f874d63fbd53fadcdd0699e21d968c8c91413b6e56) | **refused**: the window is still open |
| Renew, too early | [`0xa4db1c60...`](https://explorer-studio-dev.genlayer.com/tx/0xa4db1c60817abf908ca8f2c76c82bfd9d88b9cd94c0f779825fc3e5ed4fed7d5) | GRADE **refused**: a window in progress is not a result |
| github sample 1, 16:40 UTC | [`0x9f4dd729...`](https://explorer-studio-dev.genlayer.com/tx/0x9f4dd729e171780887c620f4127fe950650230b93a1b845ed861a1d22e15fa12) | **down**, during GitHub's incident |
| Sample again, at once | [`0xca89ee01...`](https://explorer-studio-dev.genlayer.com/tx/0xca89ee019ea8552e7d6d303e6a991356272644b6403be0da53f2f06f0e4b1b09) | **refused**, from the provider's wallet: 600 seconds apart, whoever calls |
| github sample 2, 16:54 | [`0x73296d17...`](https://explorer-studio-dev.genlayer.com/tx/0x73296d1778b098ae586198d1835f3efc452e068e8699e7a05c5a34380e630099) | **down**, still during the incident |
| github sample 3, 17:06 | [`0xaa11cc81...`](https://explorer-studio-dev.genlayer.com/tx/0xaa11cc8172cf2b0e2c791b6809d97f454b44f9619f5273fdba36f35c9e4551c5) | **up**, after recovery |
| github sample 4, 17:19 | [`0xd24f6aa9...`](https://explorer-studio-dev.genlayer.com/tx/0xd24f6aa95fae3a19f368ac19c2b718bab99d04ce1cfcd5d23b19176841bfd379) | **up**. Tally 2 of 4, 5000 basis points |
| outage samples 1 to 4 | [`0x6ab7c849...`](https://explorer-studio-dev.genlayer.com/tx/0x6ab7c849b992e622de80cb38f9bdbe0092c02ee9eb07ce79f935c31546411a1d) | **down** four times: [2](https://explorer-studio-dev.genlayer.com/tx/0x45b72c8ff73405ef53edbfd3306399f12be2b2893ac71f2d75550a9259f3c5e1), [3](https://explorer-studio-dev.genlayer.com/tx/0xf89b8c7414181d945c43a279fb3d45397c2b2b12b7fdb7a98c10041efd3a4734), [4](https://explorer-studio-dev.genlayer.com/tx/0xba9c4bd1097add64ffe8a6cae074af12d15349823e2f759e8d8b6d006a2544b1) |
| Sample after close | [`0x21783c96...`](https://explorer-studio-dev.genlayer.com/tx/0x21783c96f752388941e872c892cbd565e769f4013603e4fe208828bd260272c3) | **refused**: the window has closed, so the tally is final |
| Settle github | [`0xf625912e...`](https://explorer-studio-dev.genlayer.com/tx/0xf625912eae7555832fddbb1ddddc5c4427191ce045c22187e5a2fc04563f75de) | 2 of 4 up. Provider **5.247955 → 5.257955 GEN**, exactly half the fee. Buyer refunded the other **0.01 GEN** in the same transaction |
| Settle outage | [`0xca410458...`](https://explorer-studio-dev.genlayer.com/tx/0xca410458e7bd3108db6ccebd5ae04dc00580a707bc9e7c4e49ee3994caf4a3ea) | 0 of 4 up. Provider paid **nothing**; the whole 0.02 GEN back to the buyer. `committed` back to `0` |
| Renew | [`0x597a71c8...`](https://explorer-studio-dev.genlayer.com/tx/0x597a71c8aab8e431e24ced45d86b2b0e3c482032362f1e278db949561260f484) | GRADE **refused**: a closed window at 5000 basis points against a 9900 bar |

And the exit for a plan the provider never took:

| step | transaction | result |
|---|---|---|
| Propose and fund | [`0x2b1a5a22...`](https://explorer-studio-dev.genlayer.com/tx/0x2b1a5a224428b972b666f30b25fbb52f8d0c0250769fa5ebb3ed20e57e7ef592) | 0.02 GEN held ([fund](https://explorer-studio-dev.genlayer.com/tx/0x7ec5f94bc0dffb721759f24b8c6f6146b36721b07c4e550d254700a09cc69e0d)) |
| Withdraw | [`0x7c77312b...`](https://explorer-studio-dev.genlayer.com/tx/0x7c77312b74af476bf2f0e38db09c80fc2c521fad04bade65877f1646b8203cf0) | the provider can no longer accept it |
| Reclaim | [`0x72cf9fc3...`](https://explorer-studio-dev.genlayer.com/tx/0x72cf9fc34d14c2028f25d2f29a5714bb7d07ae15379f4ca99b9a750d35de7ec0) | buyer **37.205203 → 37.225076 GEN**, the fee back less gas |

Three rows are the ones worth checking. **Settle github** is the bill working as designed: a provider whose service was degraded for half the window is paid for half of it, and the buyer gets the rest back with no ticket and no argument. **Settle outage** is the same arithmetic at zero. **Renew** is the reference consumer refusing a bad month that the first hour of a good one would have hidden.

What the samples do not record is *why* each down reading was down. That is deliberate: consensus only agrees on the outcome, so only the outcome is stored. Each validator's own fetch is visible in its execution on the explorer.

---

## Limits, stated plainly

- **It measures the URL both sides agreed on, nothing more.** A health endpoint the provider writes reports whatever the provider wants it to. A buyer should name a URL that exercises the real service, and a marker that only a working response contains.
- **Sampling is a sample, not a census.** An outage that starts and ends between two samples is not seen. Ten minutes is the floor between samples, not a schedule.
- **Both sides choose when to sample.** Anyone may sample, and the gap applies to everyone, so neither side can crowd the other out. But a buyer who never samples is trusting the provider's choice of moments. The remedy is to sample.
- **An unreachable host is billed against the provider.** That is the right default for a bill, for the reasons above, but it does mean a fault on the network side that every validator shares at once lands on the provider. Consensus makes a single validator's bad connection harmless; a shared one is not.
- **A provider who accepts an unfunded plan is measured for nothing.** The fee must go in before acceptance, but PLAN cannot check that without reading LEDGER, and LEDGER already reads PLAN. `LEDGER.is_funded` is public and is the provider's check before accepting.
- **The window is at most a month and at least an hour**, and one plan is one window. A recurring subscription is one plan per period.

---

## Running it

```sh
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m deploy.build_bundle          # the four files that actually deploy
python -m pytest -q                    # 174 tests, no chain and no network
```

The tests run the contracts in direct mode, in process, with every fetch answered from the test, so a test can make the service healthy, broken, behind an auth wall, or gone. An unmocked fetch raises rather than going out to the network, which is how a test reaches the "could not be reached" path.

```sh
npm install
export GENLAYER_KEYSTORE=~/.genlayer/keystores/mykey.json
export GENLAYER_PASSWORD=...
node deploy/deploy.mjs contracts/plan_bundle.py
node deploy/deploy.mjs contracts/meter_bundle.py  <plan address>
node deploy/deploy.mjs contracts/ledger_bundle.py <plan address> <meter address>
node deploy/deploy.mjs contracts/grade_bundle.py  <meter address> <plan id> <basis points>
node deploy/verify.mjs                 # each live contract runs this exact bundle
```

Settling a plan that bills both sides sends two payments, so the transaction must reserve two funded external message allocations; see `deploy/chain.mjs`. Addresses live in [`deploy/live.json`](deploy/live.json). The password is read from the environment and is never stored in this repo.

---

## Layout

```
contracts/metering.py       the pure part: what a fetch means, the split, dates
contracts/plan.py           the terms both sides sign
contracts/meter.py          samples of the live service, under consensus
contracts/ledger.py         escrow and the division of the fee
contracts/grade.py          reference consumer: a renewal gated on a closed window
contracts/*_bundle.py       what actually deploys. Generated, never edited
deploy/build_bundle.py      builds them; a test fails if a committed one is stale
deploy/verify.mjs           prove a live contract runs this exact bundle
test/                       174 tests
```

GenVM loads a single source file with no access to siblings, so each bundle pastes a contract together with the pure module it imports. Comments and docstrings are stripped from the deployed copy, because a deploy costs gas per byte. Edit the modules, never a bundle: a test regenerates them and fails if a committed copy has drifted.

## License

MIT
