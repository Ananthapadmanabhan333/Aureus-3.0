# AUREUS-RV 3.0 — Quantitative Methodology

## 1. Physical Purity & Unit Normalization

MCX lists multiple gold futures contracts with differing quotation units and purities:
- **GOLD (Standard 1 kg):** Quoted in INR per 10 grams at **995 fineness** ($\text{multiplier} = 100$).
- **GOLDM (Mini 100 g):** Quoted in INR per 10 grams at **999 fineness** ($\text{multiplier} = 10$).
- **GOLDGUINEA (8 g):** Quoted in INR per 8 grams at **999 fineness** ($\text{multiplier} = 1$).
- **GOLDPETAL (1 g):** Quoted in INR per 1 gram at **999 fineness** ($\text{multiplier} = 1$).

Comparing raw prices across variants without purity and weight normalization introduces artificial basis distortions. AUREUS-RV 3.0 normalizes all comparable gold quotations to **INR per 1 gram at 999 fineness**:

$$P^{\text{norm}}_{i,t} = P^{\text{raw}}_{i,t} \times \left(\frac{999}{\text{fineness}_i}\right) \times \frac{1}{g_i}$$

For an input quoted in INR per 10 grams at 995 fineness (`GOLD`):

$$P^{\text{norm}}_{i,t} = P^{\text{raw}}_{i,t} \times \left(\frac{999}{995}\right) \Big/ 10$$

Contract lot notional is maintained strictly separately:

$$\text{Notional}_{\text{lot}, i, t} = P^{\text{raw}}_{i,t} \times \left(\frac{\text{lot\_size\_grams}_i}{g_i}\right)$$

## 2. Expiry-Aware Pairing & Tender-Period Guard

For an ordered candidate pair $(A, B)$ observed at date $d_t$ with expiries $E_A \le E_B$:
- **Days to Expiry (DTE):** $\text{DTE}_A = (E_A - d_t)$, $\text{DTE}_B = (E_B - d_t)$.
- **Expiry Gap:** $\Delta E = (E_B - E_A)$. Must satisfy $\Delta E_{\min} \le \Delta E \le \Delta E_{\max}$ (default $[7, 135]$ days).
- **Tender / Rollover Freeze:** To avoid physical delivery tender squeeze on near-month MCX contracts, any pair with $\text{DTE}_A < \max(\text{min\_dte\_near}, \text{tender\_period\_days})$ is rejected with `ERR_NEAR_LEG_IN_TENDER_OR_ROLLOVER`.

## 3. Past-Only Spread Diagnostics

At decision timestamp $T$, the aligned history is filtered strictly to $t \le T$. Over the trailing window of length $W$ (default $20$ bars):

1. **Normalized Spread (INR/g @ 999):**
   $$S_t = P^{\text{norm}}_{A,t} - P^{\text{norm}}_{B,t}$$
2. **Reference Mid & Basis Points Spread:**
   $$M_t = \frac{1}{2}\left(P^{\text{norm}}_{A,t} + P^{\text{norm}}_{B,t}\right), \qquad S^{\text{bps}}_t = \frac{S_t}{M_t} \times 10^4$$
3. **Rolling Z-Score:**
   $$\mu_T = \frac{1}{W}\sum_{k=0}^{W-1} S_{T-k}, \qquad \sigma_T = \sqrt{\frac{1}{W-1}\sum_{k=0}^{W-1}(S_{T-k} - \mu_T)^2}, \qquad Z_T = \frac{S_T - \mu_T}{\sigma_T}$$
4. **Conservative Expected Convergence:**
   When $|Z_T| > Z_{\text{exit}}$, the expected gross convergence to the exit band is:
   $$\Delta S^{\text{expected}}_T = \left(|Z_T| - Z_{\text{exit}}\right) \cdot \sigma_T$$
5. **OLS Hedge Diagnostics & Standardized Residuals:**
   Ordinary Least Squares regression $P^{\text{norm}}_{A,t} = \alpha + \beta P^{\text{norm}}_{B,t} + \epsilon_t$ is estimated on the trailing window. If $\beta \notin [0.2, 5.0]$ or $\text{Corr}(P_A, P_B) < \rho_{\min}$, the pair is rejected (`ERR_UNSTABLE_REGRESSION` or `ERR_LOW_CORRELATION`).
6. **Structural Break Stop Guard:**
   If $|Z_T| \ge Z_{\text{stop}}$ (default $4.5\sigma$), the engine abstains with `ERR_ZSCORE_EXTREME_STOP` rather than assuming mean reversion during a structural regime break.
