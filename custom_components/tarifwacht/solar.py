"""What PV and battery saved, under each tariff.

Three cases per hour and tariff (HA feature request #1065):

- without PV and battery: the whole household consumption from the grid,
- PV without battery (imagined): consumption minus PV from the grid, the
  surplus fed in,
- actual: the metered purchase, minus the feed-in revenue.

Saving by PV = without - PV only, saving by the battery = PV only - actual.
Base prices are the same in all three cases and left out.

The household consumption is derived from the meters:
- battery behind the PV inverter (hybrid inverter, DC coupled, e.g. Fronius
  Gen24, Huawei, Kostal): the PV meter is the inverter's AC output, battery
  energy included. Consumption = purchase - feed-in + inverter output; PV
  without battery = inverter output + (charged - discharged) x efficiency.
- battery with its own inverter (AC coupled): consumption = purchase -
  feed-in + PV - charged + discharged; PV without battery = PV.

Hourly energy from the long-term statistics; within an hour PV and
consumption are netted, so the PV saving comes out a little high and the
battery saving a little low (the battery covers exactly these gaps). Each
hour's energy counts in equal parts for its quarter hours, as in lookback.py.

Feed-in: a fixed rate; with `negative_unpaid` (§ 51 EEG, plants from
25.02.2025 with a smart meter) nothing in quarter hours with a negative
day-ahead price.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

from .tariffs import PriceSource, Tariff
from .timeslots import QUARTER

# Inverter efficiency for battery energy behind a hybrid inverter (DC to AC).
# Own assumption; 0.90 to 0.97 moves a year by a few euros only.
DEFAULT_EFFICIENCY = 0.95

# Coupling detection: hours with this much discharge and no charge.
DETECT_MIN_DISCHARGE = 0.2  # kWh
DETECT_MIN_HOURS = 10


@dataclass(frozen=True)
class HourFlows:
    """Metered energy of one UTC hour in kWh (all >= 0)."""

    purchase: float = 0.0
    feed_in: float = 0.0
    pv: float = 0.0
    charged: float = 0.0
    discharged: float = 0.0


@dataclass(frozen=True)
class SolarSettings:
    """How the meters are to be read and what feed-in earns."""

    # True: the PV meter is the output of a hybrid inverter with the battery.
    same_inverter: bool
    feed_in_rate: float  # EUR/kWh
    negative_unpaid: bool = False
    efficiency: float = DEFAULT_EFFICIENCY

    def consumption(self, hour: HourFlows) -> float:
        """Household consumption of the hour (never below 0)."""
        value = hour.purchase - hour.feed_in + hour.pv
        if not self.same_inverter:
            value += hour.discharged - hour.charged
        return max(0.0, value)

    def pv_alone(self, hour: HourFlows) -> float:
        """PV energy on the AC side as if there were no battery."""
        if not self.same_inverter:
            return max(0.0, hour.pv)
        return max(0.0, hour.pv + (hour.charged - hour.discharged) * self.efficiency)


@dataclass
class SolarTotals:
    """The three cases of one tariff over a period (EUR, kWh)."""

    without: float = 0.0
    pv_only: float = 0.0
    actual: float = 0.0
    consumption: float = 0.0
    pv: float = 0.0
    purchase: float = 0.0
    feed_in: float = 0.0
    feed_in_unpaid: float = 0.0  # kWh fed in at a negative price (§ 51)
    charged: float = 0.0
    discharged: float = 0.0
    hours: int = 0
    # Hours without a price of the tariff (or of the market for § 51).
    hours_left_out: int = 0

    @property
    def saving_pv(self) -> float:
        return self.without - self.pv_only

    @property
    def saving_battery(self) -> float:
        return self.pv_only - self.actual

    @property
    def saving(self) -> float:
        return self.without - self.actual

    @property
    def battery_value(self) -> float | None:
        """Saving of the battery per kWh discharged (EUR/kWh)."""
        return self.saving_battery / self.discharged if self.discharged else None


@dataclass
class SolarResult:
    """Totals per tariff, for the whole period and per local month."""

    totals: dict[str, SolarTotals]
    months: dict[str, dict[str, SolarTotals]] = field(default_factory=dict)


def _hour_prices(source: PriceSource | Tariff, hour: datetime) -> list[float] | None:
    get = source.price if isinstance(source, Tariff) else source.get
    prices = [get(hour + i * QUARTER) for i in range(4)]
    if any(p is None for p in prices):
        return None
    return prices  # type: ignore[return-value]


def book_hour(
    totals: SolarTotals,
    hour: HourFlows,
    prices: list[float],
    paid_share: float,
    settings: SolarSettings,
) -> None:
    """Add one hour: `prices` of its four quarter hours (EUR/kWh), the share
    of them in which feed-in is paid."""
    price = sum(prices) / len(prices)
    rate = settings.feed_in_rate * paid_share
    consumption = settings.consumption(hour)
    pv = settings.pv_alone(hour)
    purchase_alone = max(0.0, consumption - pv)
    feed_in_alone = max(0.0, pv - consumption)
    totals.without += consumption * price
    totals.pv_only += purchase_alone * price - feed_in_alone * rate
    totals.actual += hour.purchase * price - hour.feed_in * rate
    totals.consumption += consumption
    totals.pv += pv
    totals.purchase += hour.purchase
    totals.feed_in += hour.feed_in
    totals.feed_in_unpaid += hour.feed_in * (1 - paid_share)
    totals.charged += hour.charged
    totals.discharged += hour.discharged
    totals.hours += 1


def solar_totals(
    hours: Mapping[datetime, HourFlows],
    tariffs: Mapping[str, Tariff],
    settings: SolarSettings,
    tz: tzinfo,
    market: PriceSource | None = None,
) -> SolarResult:
    """The three cases per tariff over `hours` (UTC hour starts).

    With `settings.negative_unpaid` the market prices decide which quarter
    hours pay for feed-in; an hour without them is left out (as an hour
    without the tariff's price).
    """
    result = SolarResult(totals={key: SolarTotals() for key in tariffs})
    for start, flows in sorted(hours.items()):
        month = start.astimezone(tz).strftime("%Y-%m")
        per_month = result.months.setdefault(
            month, {key: SolarTotals() for key in tariffs}
        )
        paid_share: float | None = 1.0
        if settings.negative_unpaid:
            market_prices = _hour_prices(market, start) if market else None
            paid_share = (
                None
                if market_prices is None
                else sum(1 for p in market_prices if p >= 0) / 4
            )
        for key, tariff in tariffs.items():
            prices = _hour_prices(tariff, start)
            for totals in (result.totals[key], per_month[key]):
                if prices is None or paid_share is None:
                    totals.hours_left_out += 1
                else:
                    book_hour(totals, flows, prices, paid_share, settings)
    return result


def detect_same_inverter(hours: Mapping[datetime, HourFlows]) -> bool | None:
    """Whether the battery sits behind the PV inverter, from the data.

    In hours of discharging without charging (mostly nights), a hybrid
    inverter puts the battery energy out on its AC meter (about the discharge
    times its efficiency); a separate PV inverter shows nothing at night.
    None with too few such hours or no clear answer.
    """
    ratios = [
        h.pv / h.discharged
        for h in hours.values()
        if h.discharged >= DETECT_MIN_DISCHARGE and h.charged < 0.01
    ]
    if len(ratios) < DETECT_MIN_HOURS:
        return None
    low = statistics.quantiles(ratios, n=4)[0]
    if low >= 0.5:
        return True
    if low <= 0.1:
        return False
    return None
