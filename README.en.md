<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Tarifwacht – Every tariff. Every quarter hour." src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/tarifwacht/integration?color=96497D)](https://github.com/tarifwacht/integration/releases)
[![CI](https://github.com/tarifwacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/tarifwacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

🇩🇪 [Deutsch](https://github.com/tarifwacht/integration/blob/main/README.md) · 🇬🇧 **English**

> ℹ️ **Beta.** Tarifwacht is new and currently being tested. Feedback is very welcome – see [Reporting issues](#reporting-issues).

**What would your electricity have cost with a different tariff?** Tarifwacht ("tariff watch") prices your actual grid consumption in Home Assistant quarter hour by quarter hour against any number of tariffs – fixed price, dynamic, with or without Modul 3 – and shows which one would have been cheaper. Each dynamic tariff gets the price of **exactly that quarter hour**, not the price of whatever moment the meter happens to report.

Tarifwacht is built for Germany: quarter-hour day-ahead prices, German price components and the time-variable grid fee under § 14a EnWG. Days and months (base prices) follow German local time.

> **No billing or tariff advice.** The figures are a guide. Your supplier's bill is what counts.

The user interface is available in German and English and follows the language of your Home Assistant.

## Features

- **Cost per tariff** (€): consumption cost and total cost (including base price) – with long-term statistics for statistics cards and the energy dashboard.
- **Difference to current tariff** (€) for every other tariff. Positive means this tariff would have been more expensive; negative, cheaper.
- **Average price** per tariff (ct/kWh, including base price) and the **cheapest tariff** so far.
- **Any number of tariffs:** fixed price, dynamic with a total-price sensor, or dynamic from exchange price plus grid fee, taxes/levies, supplier surcharge and VAT.
- **Modul 3** (§ 14a EnWG): time-variable grid fee with low-load and high-load windows per quarter.
- **Price changes from a date**, e.g. new grid fees on 1 January – the old prices still apply before that date.
- **Base prices** optional, per month or per year, booked pro rata per day.
- **Comparison for any period** via an action, broken down by month – also **before the setup**, as far back as your meter's long-term statistics go: what would last year have cost with each tariff?
- **Prices every tariff from the setup on:** consumption and prices are stored per quarter hour. A tariff added or corrected later therefore applies to the whole period.
- **Loses nothing:** if the meter drops out or Home Assistant restarts, the consumption of the gap is booked afterwards. If a price is missing, Tarifwacht never uses 0 €. Meter resets and implausible jumps are detected and not booked.
- **Easy on SD cards:** writes only once per quarter hour (closed days once a day into a yearly archive) and updates the sensors at most once a minute.
- Local only: reads existing entities, no cloud. Only for looking back does Tarifwacht load public exchange prices from SMARD.de.

## Notes on the comparison

- The comparison assumes the **same consumption behaviour**. With a dynamic tariff many people shift consumption into cheap hours – the comparison cannot reflect that. It rather shows what a dynamic tariff brings *at least*.
- Enter **all price components on both sides** in the same way, otherwise the comparison is skewed. The total price of a dynamic tariff is the exchange price plus grid fee, concession fee, levies, electricity tax and supplier surcharge, plus VAT. The figures are in the price sheets of your supplier and grid operator.
- Home Assistant usually measures with its own meter (optical reader, energy meter), your supplier with the grid operator's meter. Small differences are normal.

## Requirements

- Home Assistant 2026.3 or newer.
- A **grid import meter**: a cumulative energy sensor (Wh, kWh or MWh) for the energy drawn from the grid, ideally the meter at the grid connection point.
- For dynamic tariffs a **price sensor** in €/kWh, ideally with a forecast per quarter hour or hour:

| Source (integration) | Total price | Exchange price | Status |
|---|---|---|---|
| [EPEX Spot](https://github.com/mampfes/ha_epex_spot) | `…_total_price` | `…_market_price` | tested |
| [Nord Pool](https://github.com/custom-components/nordpool) (HACS) | sensor with VAT and additional costs | sensor without VAT and additional costs | experimental |
| [ENTSO-E](https://github.com/JaccoR/hass-entso-e) (HACS) | average price sensor with surcharges | average price sensor without surcharges | experimental |

"Experimental" means: the format was reproduced from the integration's source code and real market data, but has not yet been checked on a running installation. If you use one of them, I'd appreciate feedback with the diagnostics file. Home Assistant's own Nord Pool integration does not provide a forecast attribute and is not supported.

A sensor without a forecast works too: its current value applies until it changes. If Home Assistant is not running for a while, though, the prices for that time are missing – with a forecast Tarifwacht catches up on them.

## Installation

1. HACS → ⋮ → *Custom repositories* → `https://github.com/tarifwacht/integration`, type *Integration*.
2. Search for Tarifwacht and download it. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Tarifwacht*.

## Setup

1. **Grid import meter:** name (e.g. "Home") and meter.
2. **Tariffs:** energy price of a fixed-price tariff (ct/kWh, gross) and a sensor with the total price of a dynamic tariff, for both optionally the base price per month. This creates the first two tariffs; the fixed price is "My current tariff".

### More tariffs

*Tarifwacht → Add tariff* and choose the kind:

<img alt="Choosing the kind of tariff" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/tarif-art.png" width="480">

| Kind | Inputs |
|---|---|
| Fixed price | energy price (ct/kWh, gross) |
| Dynamic: sensor with the total price | sensor that already contains all components |
| Dynamic: exchange price plus surcharges | exchange price sensor; grid fee, taxes/levies, supplier surcharge (each ct/kWh net); VAT (%) |

Every tariff has an optional base price (per month or per year) and the switch **My current tariff** – the other tariffs show their difference to this one.

### Changing a tariff

Click the cog (*Configure*) on the tariff:

- **Edit tariff:** name, current tariff and prices **from the start** – for typos and corrections. Tarifwacht recalculates the whole period.
- **Add a price change from a date:** new prices from midnight of that day (German local time), e.g. a price increase by your supplier or new grid fees. The previous prices still apply before that. The form is pre-filled with today's prices.
- **Remove a price change:** the prices before it apply again.
- **Modul 3** (only for "exchange price plus surcharges"), see below.

Several meters: add one entry each. To change the name or meter: *Tarifwacht → ⋮ → Reconfigure*.

### Modul 3 (§ 14a EnWG)

With a controllable consumer (heat pump, wallbox) you can choose Modul 3 with your grid operator: a grid fee that depends on the time of day. Whether it pays off is shown by a second tariff with the same prices and Modul 3 switched on.

<img alt="Modul 3 with low-load and high-load windows" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/modul3.png" width="480">

- **Levels:** low load (NT) and high load (HT) in ct/kWh net; outside the windows the tariff's normal grid fee applies (standard level).
- **Quarters:** in which quarters the windows apply; in the others the standard level applies all day.
- **Time windows:** local time on the quarter-hour grid, several separated by commas, also across midnight – e.g. `23:00-06:00` or `01:45-06:15, 22:30-24:00`.
- All figures are in your grid operator's price sheet. When they change (usually at the turn of the year), enter the new price sheet as a price change from its effective date.
- Modul 3 applies to the **entire** grid consumption of the metering point, not only to the heat pump or wallbox. That fits as long as the device does not have its own meter.

Basis: Bundesnetzagentur determination BK8-22/010-A; details and sources (German) in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md).

## Entities

On the meter's device (e.g. "Home"):

| Entity | Unit | Meaning |
|---|---|---|
| Grid purchase | kWh | energy recorded since setup – to check against your meter |
| Cheapest tariff | text | tariff with the lowest total cost; attribute `ranking` with all tariffs |

On every tariff (e.g. "Home Fixed price"):

| Entity | Unit | Meaning |
|---|---|---|
| Consumption cost | € | grid purchase × price of the respective quarter hour |
| Total cost | € | consumption cost plus base price |
| Average price | ct/kWh | total cost ÷ grid purchase |
| Difference to current tariff | € | total cost minus the current tariff's cost (not on the current tariff itself) |

For dynamic tariffs the consumption of a quarter hour waits up to 24 hours for its price; usually it is known since the day before.

## Dashboard: cost per month

Daily, monthly and yearly values come from the long-term statistics – no extra meters needed. Example of a statistics graph card (*Edit dashboard → Add card → Manual*); the entity IDs depend on your names:

```yaml
type: statistics-graph
title: Electricity cost per month
chart_type: bar
period: month
stat_types:
  - change
days_to_show: 365
entities:
  - entity: sensor.home_fixed_price_total_cost
    name: Fixed price
  - entity: sensor.home_dynamic_total_cost
    name: Dynamic
```

## Comparison for a period

*Settings → Tools → Actions* (formerly *Developer tools → Actions*) → **Compare tariffs**, choose the meter and period, "Show response":

```yaml
action: tarifwacht.compare
data:
  config_entry: <select entry>
  start: "2026-11-01 00:00:00"
  end: "2026-12-01 00:00:00"
```

The response contains the grid purchase and number of quarter hours in the period, the cheapest tariff and per tariff – cheapest first – the total cost, consumption and base-price cost, the average price and the difference to the current tariff; under `months` the same in short per calendar month. Without start or end: since setup or until now. Times without a time zone are taken as your Home Assistant's local time.

### Looking back before the setup

If the start lies before the setup, Tarifwacht calculates that time as well:

- **Consumption:** from your grid import meter's long-term statistics. They hold hourly values; each hour is spread evenly over its four quarter hours. Exact for a fixed price, a good approximation for dynamic prices (the exchange price changes every quarter hour since 1 October 2025).
- **Exchange prices:** from [SMARD.de](https://www.smard.de) (Bundesnetzagentur), day-ahead DE-LU – the same prices as the EPEX Spot market price. Tarifwacht loads them on the first comparison of a period (one request per week, a year takes about half a minute) and keeps them; after that no download is needed.
- **Which tariffs:** fixed price and "exchange price plus surcharges" (also with Modul 3 and price changes). A **sensor with the total price** only knows the time since setup – such tariffs are listed last with `energy_without_price_kwh`, are not counted as the cheapest and have no difference to the current tariff (`null`), since they would look cheaper than they are. Tip: add your dynamic tariff a second time as "exchange price plus surcharges".
- `estimate` shows until when it was estimated, how much energy that was and how many hours are missing in the statistics (e.g. because the meter did not exist yet); plus the SMARD.de attribution if exchange prices from there were needed.
- Prices and base prices apply as the tariff is entered today (with its price changes). For a comparison across a turn of the year, enter the old prices as a price change, e.g. last year's grid fees.

You can also use the response in scripts and automations (`response_variable`), e.g. for a monthly summary as a notification.

## Privacy

Tarifwacht calculates locally and only reads the entities you select. Only exception: if you compare a time before the setup, Tarifwacht loads public exchange prices from SMARD.de. Nothing about you is transferred – just the download of the price files with the identifier `Tarifwacht/<version>`. The diagnostics file contains your tariff settings (prices, sensors), but no names, meter readings, energy or cost totals.

## What Tarifwacht does not do

- **No billing:** differences to your bill are normal (different meter, rounding, instalments).
- **No changed behaviour:** the comparison prices your actual consumption – what you would shift with a dynamic tariff is not visible to it.
- **Sensors start at setup:** the time before is only available through the action Compare tariffs, not in statistics cards.
- **No grid feed-in:** Tarifwacht only prices grid consumption. For feed-in there is the sister project [Einspeisewacht](https://github.com/einspeisewacht/integration).
- **Modul 1 and 2** under § 14a EnWG are not modelled separately.

## Troubleshooting

Tarifwacht reports problems under *Settings → Repairs*:

- **Price sensor with an unsupported unit:** the sensor delivers e.g. ct/kWh or €/MWh. Tarifwacht needs €/kWh and ignores its prices until then.
- **Meter with an unsupported unit:** Tarifwacht books nothing until the meter delivers Wh, kWh or MWh.
- **Prices missing:** the price of a past quarter hour is missing; the price integration has probably failed. After 24 hours the consumption is counted without a price – never as free.

Further:

- **Values stay at 0:** does the grid import meter deliver values? "Grid purchase" should grow along with your meter.
- **Dynamic costs lag behind:** a quarter hour is booked only once its price is known. With a forecast that is immediately; otherwise see "Prices missing".
- **Diagnostics:** *Tarifwacht → entry → ⋮ → Download diagnostics*. **Debug log:** *Tarifwacht → ⋮ → Enable debug logging*.

**Update from 0.1.0b1:** the two tariffs become separate tariff entries, the consumption since setup is read once from the history (recorder). The sensors keep their entity IDs; "Extra cost dynamic" is now "Difference to current tariff".

## Removal

1. *Settings → Devices & services → Tarifwacht* → on every entry ⋮ → *Delete*. The stored quarter hours of this entry are deleted with it.
2. Optional: HACS → Tarifwacht → ⋮ → *Remove*, then restart Home Assistant.

The long-term statistics of the deleted sensors stay in Home Assistant until you remove them under *Settings → Tools → Statistics* (formerly *Developer tools*).

## Reporting issues

Please open an [issue](https://github.com/tarifwacht/integration/issues) – ideally with the diagnostics file and the versions of Home Assistant and Tarifwacht. Please report security issues privately, see [SECURITY.md](SECURITY.md).

## Thanks

The idea of pricing your own consumption directly against both tariffs in Home Assistant comes from [tariff_compare](https://github.com/fischit87/tariff_compare) by fischit87.

## License

MIT. Historical exchange prices (only for comparisons before the setup): Bundesnetzagentur | [SMARD.de](https://www.smard.de), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The images in this README show a demo entry with invented consumption and invented prices.
