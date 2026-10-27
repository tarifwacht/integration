<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Tarifwacht – Every tariff. Every quarter hour." src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/tarifwacht/integration?color=96497D)](https://github.com/tarifwacht/integration/releases)
[![CI](https://github.com/tarifwacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/tarifwacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

🇩🇪 [Deutsch](https://github.com/tarifwacht/integration/blob/main/README.md) · 🇬🇧 **English**

> ℹ️ **New.** Tarifwacht is new and currently being tested. Feedback is very welcome – see [Reporting issues](#reporting-issues).

**What would your electricity have cost with a different tariff?** Tarifwacht ("tariff watch") prices your actual grid consumption in Home Assistant quarter hour by quarter hour against any number of tariffs – fixed price, dynamic, with or without Modul 3 – and shows which one would have been cheaper. Each dynamic tariff gets the price of **exactly that quarter hour**, not the price of whatever moment the meter happens to report.

Tarifwacht is built for Germany: quarter-hour day-ahead prices, German price components and the time-variable grid fee under § 14a EnWG. Days and months (base prices) follow German local time.

> **No billing or tariff advice.** The figures are a guide. Your supplier's bill is what counts.

The user interface is available in German and English and follows the language of your Home Assistant.

<img alt="Device of a tariff with costs, average price and difference to the current tariff" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/geraet.png" width="640">

## Features

- **Cost per tariff** (€): consumption cost and total cost (including base price) – with long-term statistics for statistics cards and the energy dashboard.
- **Difference to current tariff** (€) for every other tariff. Positive means this tariff would have been more expensive; negative, cheaper.
- **Average price** per tariff (ct/kWh, including base price) and the **cheapest tariff** so far.
- **Any number of tariffs:** fixed price, dynamic with a total-price sensor, or dynamic from exchange price plus grid fee, taxes/levies, supplier surcharge and VAT.
- **Modul 3** (§ 14a EnWG): time-variable grid fee with low-load and high-load windows per quarter.
- **Price changes from a date**, e.g. new grid fees on 1 January – the old prices still apply before that date.
- **Base prices** optional, per month or per year, booked pro rata per day.
- **Comparison for any period** via an action, broken down by month – also **before the setup**, as far back as your meter's long-term statistics go: what would last year have cost with each tariff? On request also [written into the long-term statistics](#import-statistics).
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
2. **Fixed-price tariff:** energy price (ct/kWh, gross), optionally the base price per month. It becomes "My current tariff".
3. **Dynamic tariff:** first choose the kind – **exchange price plus surcharges** (recommended, see [Adding a dynamic tariff](#adding-a-dynamic-tariff)) or a sensor with the total price (calculates only from the setup on) –, then the prices.

This creates the first two tariffs. If you set up Tarifwacht before 0.1.0 with a total price sensor: add the dynamic tariff a second time as "exchange price plus surcharges", then you can delete the old one.

### More tariffs

*Tarifwacht → Add tariff* and choose the kind:

<img alt="Choosing the kind of tariff" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/tarif-art.png" width="480">

| Kind | Inputs |
|---|---|
| Fixed price | energy price (ct/kWh, gross) |
| Dynamic: sensor with the total price | sensor that already contains all components – calculates only from the setup on |
| Dynamic: exchange price plus surcharges | exchange price sensor; grid fee, taxes/levies, supplier surcharge (each ct/kWh net); VAT (%) |

Every tariff has an optional base price (per month or per year) and the switch **My current tariff** – the other tariffs show their difference to this one.

### Adding a dynamic tariff

Choose **exchange price plus surcharges**. Only then can Tarifwacht also calculate the time before the setup ([looking back](#looking-back-before-the-setup), [import statistics](#import-statistics)) – the exchange prices of that time come from SMARD.de. A sensor with the total price only knows the time since setup.

If you set a surcharge and a tax in **EPEX Spot**, simply copy these values – the tariff then calculates exactly like EPEX Spot's total price:

| In EPEX Spot | In Tarifwacht |
|---|---|
| sensor with the market price (Market Price) | sensor with the exchange price |
| absolute surcharge, e.g. 0.15 €/kWh | supplier surcharge **15** ct/kWh (Tarifwacht uses cents: € × 100) |
| tax, e.g. 19 % | VAT 19 % |

Leave grid fee and taxes/levies empty – they are already in the surcharge. Checked for an absolute surcharge; a percentage surcharge has not been verified yet. Once you have the price sheets, you can split the surcharge later (*Edit tariff*).

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
| Cheapest tariff | text | tariff with the lowest total cost; attribute `ranking` with all tariffs (missing prices: see below) |

On every tariff (e.g. "Home Fixed price"):

| Entity | Unit | Meaning |
|---|---|---|
| Consumption cost | € | grid purchase × price of the respective quarter hour |
| Total cost | € | consumption cost plus base price |
| Average price | ct/kWh | total cost ÷ grid purchase |
| Difference to current tariff | € | total cost minus the current tariff's cost (not on the current tariff itself; missing prices: see below) |

For dynamic tariffs the consumption of a quarter hour waits up to 24 hours for its price; usually it is known since the day before.

## Dashboard: tariff comparison

Daily, monthly and yearly values come from the long-term statistics – no extra meters needed. A ready-made section for a sections view: cheapest tariff, average prices, cost today and this month, the difference and a bar chart per day. Four cards side by side on a desktop, two on a phone. *Edit dashboard → Add section → ⋮ → Edit in code editor*; the entity IDs depend on your names (here meter "Home", tariffs "Fixed price" and "Dynamic"):

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Tariff comparison
    icon: mdi:scale-balance
  - type: tile
    entity: sensor.home_cheapest_tariff
    name: Cheapest tariff
    grid_options: {columns: 12}
  - type: tile
    entity: sensor.home_fixed_price_average_price
    name: Avg. fixed price
    grid_options: {columns: 6}
  - type: tile
    entity: sensor.home_dynamic_average_price
    name: Avg. dynamic
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.home_fixed_price_total_cost
    name: Fixed price today
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.home_dynamic_total_cost
    name: Dynamic today
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.home_fixed_price_total_cost
    name: Fixed price this month
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.home_dynamic_total_cost
    name: Dynamic this month
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.home_dynamic_difference_to_current_tariff
    name: Difference today
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 12}
  - type: statistic
    entity: sensor.home_dynamic_difference_to_current_tariff
    name: Difference this month
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 12}
  - type: heading
    heading_style: subtitle
    heading: "Positive difference: dynamic would have cost more"
  - type: statistics-graph
    title: Cost per day
    chart_type: bar
    period: day
    days_to_show: 30
    stat_types: [change]
    entities:
      - entity: sensor.home_fixed_price_total_cost
        name: Fixed price
      - entity: sensor.home_dynamic_total_cost
        name: Dynamic
    grid_options: {columns: full}
```

For a yearly overview in the chart, use `period: month` and `days_to_show: 365`. With [import statistics](#import-statistics) the cards also show the time before the setup.

## Comparison for a period

*Settings → Tools → Actions* (formerly *Developer tools → Actions*) → **Compare tariffs**, choose the meter and period, "Show response":

```yaml
action: tarifwacht.compare
data:
  config_entry: <select entry>
  start: "2026-11-01 00:00:00"
  end: "2026-12-01 00:00:00"
```

<img alt="Response of the action Compare tariffs" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/vergleich.png" width="640">

The response contains the grid purchase and number of quarter hours in the period, the cheapest tariff and per tariff – cheapest first – the total cost, consumption and base-price cost, the average price and the difference to the current tariff; under `months` the same in short per calendar month. Without start or end: since setup or until now. Times without a time zone are taken as your Home Assistant's local time.

### Looking back before the setup

If the start lies before the setup, Tarifwacht calculates that time as well:

- **Consumption:** from your grid import meter's long-term statistics. They hold hourly values; each hour is spread evenly over its four quarter hours. Exact for a fixed price, a good approximation for dynamic prices (the exchange price changes every quarter hour since 1 October 2025).
- **Exchange prices:** from [SMARD.de](https://www.smard.de) (Bundesnetzagentur), day-ahead DE-LU – the same prices as the EPEX Spot market price. Tarifwacht loads them on the first comparison of a period (one request per week, a year takes about half a minute) and keeps them; after that no download is needed.
- **Which tariffs:** fixed price and "exchange price plus surcharges" (also with Modul 3 and price changes). A **sensor with the total price** only knows the time since setup – such tariffs are listed last with `energy_without_price_kwh`, are not counted as the cheapest and have no difference to the current tariff (`null`), since they would look cheaper than they are. Tip: add your dynamic tariff as "exchange price plus surcharges", see [Adding a dynamic tariff](#adding-a-dynamic-tariff).
- `estimate` shows until when it was estimated, how much energy that was and how many hours are missing in the statistics (e.g. because the meter did not exist yet); plus the SMARD.de attribution if exchange prices from there were needed.
- Prices and base prices apply as the tariff is entered today (with its price changes). For a comparison across a turn of the year, enter the old prices as a price change, e.g. last year's grid fees.

You can also use the response in scripts and automations (`response_variable`) – ready-made as a blueprint (texts in German):

| Blueprint | What it does | |
| --- | --- | --- |
| **Monthly summary** (Monatsübersicht) | on the first of each month, sends the previous month's grid purchase, the cost of each tariff, the difference to the current tariff and the cheapest tariff – as a notification in Home Assistant or with an action of your own (e.g. to your phone) | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftarifwacht%2Fintegration%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ftarifwacht%2Fmonatsuebersicht.yaml) |

## Import statistics

The sensors only have long-term statistics from the setup on. So that statistics cards and graphs (e.g. the [tariff comparison](#dashboard-tariff-comparison)) also show the time before, there is the action **Tarifwacht: Import statistics** (*Settings → Tools → Actions*, formerly *Developer tools → Actions*):

```yaml
action: tarifwacht.import_statistics
data:
  config_entry: <choose the meter>
  start: "2026-01-01"
```

- It calculates like [looking back](#looking-back-before-the-setup) and writes the hours **before** the first existing statistic into the long-term statistics of grid purchase, consumption cost, total cost and difference; the later sums are shifted to match. A tariff added later thus also gets the time since setup.
- The start must be before the setup; it cannot go back further than your meter's long-term statistics (the response names the actual start).
- A tariff lacking prices in the period – such as a **sensor with the total price** – is skipped entirely and listed under `skipped`: better no history than one with gaps.
- Imported hours stay as written: if you later correct a tariff's prices, sensors and the action recalculate, the imported statistics do not. To redo them, delete the statistics of that tariff's sensors (*Tools → Statistics*) and import again.
- **This changes the statistics database – create a backup first.** A second call finds nothing left to import.

## Privacy

Tarifwacht calculates locally and only reads the entities you select. Only exception: if you compare a time before the setup, Tarifwacht loads public exchange prices from SMARD.de. Nothing about you is transferred – just the download of the price files with the identifier `Tarifwacht/<version>`. The diagnostics file contains your tariff settings (prices, sensors), but no names, meter readings, energy or cost totals.

## What Tarifwacht does not do

- **No billing:** differences to your bill are normal (different meter, rounding, instalments).
- **No changed behaviour:** the comparison prices your actual consumption – what you would shift with a dynamic tariff is not visible to it.
- **Sensors start at setup:** the time before is available through the action Compare tariffs and – for statistics cards – through [Import statistics](#import-statistics).
- **No grid feed-in:** Tarifwacht only prices grid consumption. For feed-in there is the sister project [Einspeisewacht](https://github.com/einspeisewacht/integration).
- **Modul 1 and 2** under § 14a EnWG are not modelled separately.

## Troubleshooting

Tarifwacht reports problems under *Settings → Repairs*:

- **Price sensor with an unsupported unit:** the sensor delivers e.g. ct/kWh or €/MWh. Tarifwacht needs €/kWh and ignores its prices until then.
- **Meter with an unsupported unit:** Tarifwacht books nothing until the meter delivers Wh, kWh or MWh.
- **Prices missing:** the price of a past quarter hour is missing; the price integration has probably failed. After 24 hours the consumption is counted without a price – never as free. So that the affected tariff does not look cheaper, "Difference to current tariff" and "Cheapest tariff" leave such quarter hours out for all tariffs; how much energy that was is in the attribute `energy_left_out_kwh`.

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
