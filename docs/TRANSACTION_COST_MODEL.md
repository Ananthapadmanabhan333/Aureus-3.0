# AUREUS-RV 3.0 — Two-Leg Transaction-Cost Waterfall Model

## 1. Cost Structure Overview

A relative-value spread trade involves two legs (Near Leg $A$ and Far Leg $B$) and four distinct executions over a complete round-trip:
1. **Entry on Leg A** + **Exit on Leg A** (1 Buy execution + 1 Sell execution on Leg A)
2. **Entry on Leg B** + **Exit on Leg B** (1 Buy execution + 1 Sell execution on Leg B)

Regardless of whether the spread position is `SHORT_SPREAD` (Sell $A$, Buy $B$ at entry; Buy $A$, Sell $B$ at exit) or `LONG_SPREAD` (Buy $A$, Sell $B$ at entry; Sell $A$, Buy $B$ at exit), **each leg executes exactly one Buy and one Sell over its round-trip**.

## 2. Per-Leg Round-Trip Equations (INR per gram @ 999)

For a leg with normalized price $P$ (INR/g @ 999) and observed bid-ask spread $s_{\text{ba}}$ (in bps, where $1\text{ bps} = 10^{-4}$):

1. **Brokerage (2 executions):**
   $$C_{\text{brok}} = 2 \cdot P \cdot \left(r_{\text{brok, bps}} \times 10^{-4}\right)$$
2. **MCX Exchange Transaction Charge (2 executions):**
   $$C_{\text{exch}} = 2 \cdot P \cdot \left(r_{\text{exch, bps}} \times 10^{-4}\right)$$
3. **SEBI Turnover Fee (2 executions):**
   $$C_{\text{sebi}} = 2 \cdot P \cdot \left(r_{\text{sebi, bps}} \times 10^{-4}\right)$$
4. **GST (18% on Brokerage + Exchange + SEBI only; never on CTT or Stamp Duty):**
   $$C_{\text{gst}} = 0.18 \times \left(C_{\text{brok}} + C_{\text{exch}} + C_{\text{sebi}}\right)$$
5. **Commodity Transaction Tax — CTT (Sell execution ONLY = 1 execution):**
   $$C_{\text{ctt}} = 1 \cdot P \cdot \left(r_{\text{ctt, bps}} \times 10^{-4}\right)$$
6. **Stamp Duty (Buy execution ONLY = 1 execution):**
   $$C_{\text{stamp}} = 1 \cdot P \cdot \left(r_{\text{stamp, bps}} \times 10^{-4}\right)$$
7. **Bid-Ask Spread Crossing (Half-spread at entry + Half-spread at exit = 1 full spread $\times m_{\text{spread}}$):**
   $$C_{\text{spread}} = P \cdot \left(s_{\text{ba}} \times 10^{-4}\right) \cdot m_{\text{spread}}$$
8. **Execution Slippage (2 executions):**
   $$C_{\text{slip}} = 2 \cdot P \cdot \left(r_{\text{slip, bps}} \times 10^{-4}\right)$$

Total single-leg round-trip cost per gram:

$$C_{\text{leg}} = C_{\text{brok}} + C_{\text{exch}} + C_{\text{sebi}} + C_{\text{gst}} + C_{\text{ctt}} + C_{\text{stamp}} + C_{\text{spread}} + C_{\text{slip}}$$

Total two-leg pair round-trip cost per gram:

$$C_{\text{pair}} = C_{\text{leg}, A} + C_{\text{leg}, B}$$

## 3. Configured Multi-Scenario Presets

| Component | Statutory / Research Basis | Base (`base`) | Conservative (`conservative`) | Stress (`stress`) |
| :--- | :--- | ---: | ---: | ---: |
| **CTT (Sell leg only)** | Statutory Indian Non-Agri Futures (0.01%) | `1.00 bps` | `1.00 bps` | `1.00 bps` |
| **Stamp Duty (Buy leg only)** | Statutory Futures Stamp Duty (0.002%) | `0.20 bps` | `0.20 bps` | `0.20 bps` |
| **SEBI Turnover Fee** | Statutory SEBI Fee (Rs 10 / crore) | `0.01 bps` | `0.01 bps` | `0.01 bps` |
| **MCX Exchange Charge** | Tariff Assumption (Rs 260 / crore) | `0.26 bps` | `0.26 bps` | `0.26 bps` |
| **Brokerage (per execution)** | Configurable Research Assumption | `0.30 bps` | `0.60 bps` | `1.00 bps` |
| **GST Fraction** | Statutory GST on Services (18%) | `18.0%` | `18.0%` | `18.0%` |
| **Slippage (per execution)** | Configurable Research Assumption | `0.50 bps` | `1.00 bps` | `2.00 bps` |
| **Half-Spread Multiplier** | Configurable Research Assumption | `1.00x` | `1.25x` | `1.75x` |

## 4. Economic Viability Gate (G5)

A statistical anomaly passes Gate G5 if and only if:
1. $\text{Net Edge} = \Delta S^{\text{expected}} - C_{\text{pair}} > 0$ (otherwise `NO_EDGE_COSTS_EXCEED_SPREAD`),
2. $\text{Net Edge (bps)} \ge \text{min\_net\_edge\_bps}$ (default $1.50\text{ bps}$, otherwise `NO_EDGE_BELOW_MIN_NET_BPS`), and
3. $\Delta S^{\text{expected}} / C_{\text{pair}} \ge \text{min\_gross\_to\_cost\_ratio}$ (default $1.25\times$, otherwise `NO_EDGE_INSUFFICIENT_NET_RATIO`).
