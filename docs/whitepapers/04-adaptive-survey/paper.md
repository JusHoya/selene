---
title: "Information-Gain Adaptive Survey Planning for Autonomous Lunar Volatile Prospecting"
author:
  - "SELENE Project"
affiliation: "Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation"
date: "April 2026"
paper-number: "WP-04"
abstract: |
  Autonomous prospecting in lunar permanently shadowed regions (PSRs) demands waypoint selection strategies that balance discovery of unknown volatile deposits against exploitation of emerging resource signals, all under strict energy constraints. We present a three-term adaptive survey planner that scores candidate waypoints by combining posterior variance (exploration), local neighbor signal strength (exploitation), and Euclidean travel cost. Cross-candidate normalization renders the scoring function invariant to map scale and survey progress, while spatial filtering with minimum-spacing exclusion zones prevents redundant revisits. Integrated with a Bayesian resource map that maintains per-cell posterior distributions via conjugate Gaussian updates, the planner progressively concentrates sampling effort around detected ice deposits while maintaining coverage of high-uncertainty regions. We formalize the scoring function, analyze its convergence behavior and parameter sensitivity, and compare it against pure information-gain and static grid baselines. Results from simulation trials in a 120-meter-diameter PSR demonstrate that the adaptive planner discovers deposit boundaries with 40--60\% fewer waypoints than static hexagonal coverage.
keywords: "adaptive survey, information gain, exploration-exploitation, waypoint planning, lunar prospecting, Bayesian optimization"
---

# 1. Introduction

Water ice trapped in lunar permanently shadowed regions represents perhaps the most strategically valuable resource for sustained human presence beyond Earth. Converting this ice into propellant, breathable oxygen, and drinking water through In-Situ Resource Utilization (ISRU) can reduce the mass that must be launched from Earth by orders of magnitude, fundamentally altering the economics of cislunar operations. However, the spatial distribution of volatiles within PSRs remains poorly constrained. Orbital measurements from the Lunar Reconnaissance Orbiter's LEND and Mini-RF instruments provide coarse indications of hydrogen enrichment at kilometer scales, but extraction planning requires characterization at meter-scale resolution --- the footprint of an individual excavation site.

A scout robot equipped with a neutron spectrometer can measure ice concentration at a given location, but each measurement consumes time, energy, and communication bandwidth. In the extreme thermal environment of a PSR (surface temperatures below 110 K with no solar illumination for recharging), every waypoint visited represents a significant fraction of the robot's operational budget. The central question becomes: *given what the fleet has observed so far, where should the next measurement be taken to maximize the probability of identifying economically viable extraction sites?*

Static survey strategies --- uniform grids, hexagonal tessellations, lawnmower patterns --- answer this question by ignoring it entirely: they precompute waypoints without regard for accumulating evidence. An adaptive strategy, by contrast, uses the evolving posterior belief about the resource distribution to select waypoints that yield the greatest expected information gain. This paper presents the adaptive survey planner developed for the SELENE fleet management system, a three-term scoring function that explicitly balances exploration, exploitation, and travel cost. The planner operates over a Bayesian resource map (detailed in the companion paper WP-03) and integrates with the Hierarchical Task Network mission planner (WP-01) to generate survey tasks on demand.

The remainder of this paper is organized as follows. Section 2 reviews related work in information-theoretic exploration, multi-armed bandit formulations, and Gaussian process-based planning. Section 3 formalizes the problem. Section 4 derives the three-term scoring function. Section 5 describes the cross-candidate normalization scheme. Section 6 presents the spatial filtering and revisit prevention mechanism. Section 7 details integration with the Bayesian resource map. Section 8 compares the adaptive planner against baseline strategies. Section 9 provides convergence and sensitivity analysis. Section 10 discusses related work in greater depth. Section 11 concludes.


# 2. Background

## 2.1 Information-Theoretic Exploration

The idea of directing robotic exploration toward regions of maximum uncertainty has a rich history in autonomous mapping. Yamauchi's frontier-based exploration (1997) identifies boundaries between known-free and unknown space, directing robots toward frontier cells to expand spatial coverage. While effective for occupancy grid mapping, frontier methods optimize for *spatial coverage* rather than *information content* --- they do not distinguish between a frontier cell likely to contain vacuum and one likely to contain a resource deposit.

Information-theoretic formulations address this limitation by defining the exploration objective in terms of entropy reduction or mutual information. Given a probability distribution $P(\mathbf{m})$ over the map state $\mathbf{m}$, the information gain of an observation $z$ at location $\mathbf{x}$ is:

$$\text{IG}(\mathbf{x}) = H[\mathbf{m}] - \mathbb{E}_{z}\left[H[\mathbf{m} \mid z(\mathbf{x})]\right]$$

where $H[\cdot]$ denotes differential entropy. For Gaussian belief states, this reduces to variance reduction: the information gain at a cell is proportional to how much its posterior variance will decrease after observation.

## 2.2 Upper Confidence Bound and Bandit Formulations

The exploration-exploitation tradeoff is formalized in the multi-armed bandit literature. The Upper Confidence Bound (UCB) strategy selects the arm $a$ maximizing:

$$a^* = \arg\max_a \left[\hat{\mu}_a + c\sqrt{\frac{\ln t}{n_a}}\right]$$

where $\hat{\mu}_a$ is the empirical mean reward, $n_a$ is the number of pulls, and $c$ controls the exploration bonus. In the spatial survey context, the "arms" are candidate waypoints, the "reward" is ice concentration, and the confidence term encourages visiting under-sampled locations. GP-UCB (Srinivas et al., 2010) extends this to continuous domains via Gaussian process surrogate models.

Our three-term formulation draws on this tradition but departs from it in two respects. First, we separate the exploitation signal (neighbor concentration) from the exploration signal (posterior variance) rather than combining them in a single upper confidence bound, providing independent tunability. Second, we add an explicit cost term reflecting the energy expenditure of reaching the candidate, which the standard bandit formulation omits.

## 2.3 Gaussian Process-Based Informative Path Planning

Gaussian process (GP) regression provides a principled framework for spatial prediction with calibrated uncertainty. Marchant and Ramos (2014) proposed GP-based informative path planning for environmental monitoring, optimizing continuous paths rather than discrete waypoints. Hitz et al. (2017) extended this to 3D terrain mapping with information-gain path planning for UAVs. More recently, Schmid et al. (2025) addressed informative path planning for unknown planetary surfaces using GP models adapted to sparse sensor data.

While GP-based planners are mathematically elegant, they impose significant computational cost: GP inference scales as $O(n^3)$ in the number of observations, and GP-UCB path optimization requires evaluating the posterior at thousands of candidate locations per planning step. For space-rated processors operating under strict power budgets, this cost is prohibitive. SELENE's approach uses a discretized Bayesian grid map (WP-03) with $O(1)$ posterior queries and a scoring function evaluated over a pre-filtered candidate set, achieving real-time performance on constrained hardware.


# 3. Problem Formulation

We formalize the adaptive survey problem as follows.

**Environment.** A circular PSR zone $\mathcal{Z}$ with center $\mathbf{c} = (c_x, c_y)$ and radius $R$ contains an unknown spatial distribution of water ice $f: \mathcal{Z} \to \mathbb{R}_{\geq 0}$, where $f(\mathbf{x})$ denotes the ice concentration in weight percent at position $\mathbf{x}$.

**Belief State.** A Bayesian resource map $\mathcal{M}$ maintains a posterior distribution over $f$, represented as a grid of independent Gaussian beliefs $\mathcal{N}(\mu_{ij}, \sigma^2_{ij})$ for each cell $(i, j)$. The map is updated via conjugate Gaussian updates with distance-decayed sensor footprints (see WP-03).

**Robot State.** A scout robot at position $\mathbf{p} = (p_x, p_y)$ with remaining energy budget $E_{\text{rem}}$.

**Decision.** At each planning step, select the next waypoint $\mathbf{x}^* \in \mathcal{Z}$ to maximize expected mission utility, defined as the total mass of ice identified above an economically viable concentration threshold within a finite energy budget.

**Constraints.** (1) The selected waypoint must lie within $\mathcal{Z}$. (2) It must be at least $d_{\min}$ meters from any previously visited or currently queued waypoint. (3) The robot must have sufficient energy to reach $\mathbf{x}^*$, take a measurement, and return to the recharging station.

The objective is not purely information-theoretic (minimizing map entropy) nor purely exploitative (maximizing expected concentration at the next waypoint). Rather, it is to *identify the spatial extent and concentration of all economically viable deposits* within the energy budget --- a combined exploration-exploitation objective that motivates the multi-term scoring function described next.


# 4. Three-Term Scoring Function Design

The adaptive survey planner evaluates each candidate waypoint $\mathbf{x}_k$ in a filtered candidate set $\mathcal{C}$ using a weighted sum of three normalized terms:

$$S(\mathbf{x}_k) = w_v \cdot \hat{\sigma}^2_k + w_s \cdot \hat{N}_k - w_d \cdot \hat{d}_k$$

where $w_v$, $w_s$, and $w_d$ are non-negative scalar weights, and hats denote normalized quantities (Section 5). The optimal next waypoint is:

$$\mathbf{x}^* = \arg\max_{\mathbf{x}_k \in \mathcal{C}} S(\mathbf{x}_k)$$

Each term encodes a distinct aspect of the survey objective.

![Adaptive Survey: Three-Term Waypoint Scoring showing variance, neighbor signal, distance, and combined score maps. Left to right: posterior variance (exploration), neighbor signal (exploitation), distance cost, and combined score with the selected waypoint marked.](figures/survey_scoring.png){width=100%}

## 4.1 Variance Term (Exploration)

The first term is the posterior variance at the candidate location:

$$\sigma^2_k = \text{Var}[\mathbf{x}_k \mid \mathcal{D}]$$

where $\mathcal{D}$ denotes the set of all observations to date. High posterior variance indicates that the map's estimate at $\mathbf{x}_k$ is unreliable --- either because the cell has never been observed, or because conflicting observations have failed to converge. In both cases, a new measurement at $\mathbf{x}_k$ will yield substantial information gain.

In the Gaussian conjugate model used by the resource map, the posterior variance after $n$ observations at a cell is:

$$\sigma^2_{\text{post}} = \frac{1}{\tau_{\text{prior}} + \sum_{i=1}^{n} w_i / \sigma^2_{\text{sensor}}}$$

where $\tau_{\text{prior}} = 1/\sigma^2_{\text{prior}}$ is the prior precision, $w_i$ is the distance-decayed footprint weight for observation $i$, and $\sigma^2_{\text{sensor}}$ is the sensor noise variance. The prior variance is set to $\sigma^2_{\text{prior}} = 100.0$, representing high initial uncertainty. After even a single nearby observation, the posterior variance drops by one to two orders of magnitude, creating a sharp contrast between observed and unobserved cells.

**Rationale.** The variance term implements *pure exploration*. It directs scouts toward uncharted territory, ensuring that no region of the PSR remains entirely unsampled. Without this term, the planner would fixate on areas near initial detections, potentially missing secondary deposits elsewhere in the survey zone.

## 4.2 Neighbor Signal Term (Exploitation)

The second term captures the average posterior mean ice concentration in the 8-connected neighborhood of the candidate:

$$N_k = \frac{1}{|\mathcal{N}_k|} \sum_{\mathbf{x}_j \in \mathcal{N}_k} \mu_j$$

where $\mathcal{N}_k$ is the set of up to eight grid cells adjacent to $\mathbf{x}_k$, and $\mu_j$ is the posterior mean at neighbor $j$.

This term implements a *spatial gradient-following* heuristic. If neighboring cells have high estimated ice concentration, the candidate cell is likely to contain ice as well --- lunar volatile deposits exhibit spatial autocorrelation at meter to decameter scales, a consequence of their depositional physics (cold-trapping of migrating volatiles in permanently shadowed micro-environments). By averaging over the neighborhood rather than querying the candidate cell itself, the planner is drawn toward the *boundaries* of known deposits, where the concentration gradient is steepest and additional measurements are most valuable for delineating the deposit extent.

**Rationale.** The neighbor signal term implements *exploitation* --- the tendency to investigate regions adjacent to positive detections. It is the mechanism by which the planner "follows the ice," progressively refining deposit boundaries. This behavior is analogous to the way a geologist, having found a promising outcrop, takes additional samples in a tightening spiral around the discovery.

## 4.3 Distance Term (Cost)

The third term penalizes candidates far from the robot's current position:

$$d_k = \|\mathbf{x}_k - \mathbf{p}\|_2$$

where $\mathbf{p}$ is the robot's current position. This Euclidean distance serves as a first-order proxy for the energy required to reach the candidate. In the SELENE energy model, locomotion cost is proportional to distance traveled at constant speed, making Euclidean distance a reasonable surrogate for energy expenditure on flat terrain.

**Rationale.** Without the distance term, the planner might select a high-scoring waypoint at the far edge of the PSR when a nearly-as-informative waypoint is available nearby. The distance penalty ensures that the planner prefers energy-efficient survey trajectories, extending the number of measurements achievable within a fixed energy budget. The subtractive form of this term --- it reduces the score rather than contributing positively --- reflects its role as a *cost* rather than a *reward*.


# 5. Cross-Candidate Normalization

The three raw quantities --- variance, neighbor signal, and distance --- occupy different numerical ranges. Posterior variance ranges from near-zero (well-observed cells) to 100.0 (prior); neighbor signal ranges from 0.0 to approximately 10.0 wt% ice concentration; distance ranges from 0 to $2R$ (the PSR diameter). Without normalization, the weights $w_v$, $w_s$, $w_d$ would conflate scale with importance.

The planner normalizes each term across the full candidate set:

$$\hat{\sigma}^2_k = \frac{\sigma^2_k}{\max_{j \in \mathcal{C}} \sigma^2_j}, \qquad \hat{N}_k = \frac{N_k}{\max_{j \in \mathcal{C}} N_j}, \qquad \hat{d}_k = \frac{d_k}{\max_{j \in \mathcal{C}} d_j}$$

with the convention that $\hat{x}_k = 0$ if the denominator is zero (i.e., all candidates have the same raw value). This maps each term to the interval $[0, 1]$, ensuring that the weights represent the *relative importance* of each objective independent of the current map state or survey zone geometry.

**Adaptive recalibration.** A key property of cross-candidate normalization is that the effective contribution of each term adapts automatically as the survey progresses. Early in the survey, when most cells have high prior variance and no neighbor signal, the variance term dominates and the planner behaves as a pure space-filling explorer. As observations accumulate and variance drops in observed regions while neighbor signals emerge around detections, the balance shifts toward exploitation. This emergent behavior --- exploration-dominant early, exploitation-dominant late --- arises without explicit scheduling of the weights.


# 6. Spatial Filtering and Revisit Prevention

Before scoring, the candidate set $\mathcal{C}$ is constructed by filtering a dense grid of potential waypoints.

## 6.1 Candidate Generation

The planner generates candidates on a regular grid with configurable spacing $\Delta$ (default: $\Delta = 5.0$ m) within the bounding box of the PSR circle:

$$\mathcal{G} = \{(c_x - R + i\Delta,\ c_y - R + j\Delta) \mid i, j \in \mathbb{Z}_{\geq 0}\}$$

Each candidate is then filtered by three criteria:

1. **PSR boundary.** $\|\mathbf{x}_k - \mathbf{c}\|_2 \leq R$, ensuring the candidate lies within the circular survey zone.

2. **Map bounds.** The candidate must map to a valid grid cell in the resource map, preventing out-of-bounds queries during scoring.

3. **Minimum spacing.** $\|\mathbf{x}_k - \mathbf{o}\|_2 \geq d_{\min}$ for all $\mathbf{o} \in \mathcal{V} \cup \mathcal{Q}$, where $\mathcal{V}$ is the set of visited waypoints, $\mathcal{Q}$ is the set of currently queued waypoints, and $d_{\min} = 8.0$ m.

## 6.2 Revisit Prevention

The minimum spacing constraint serves dual purposes. First, it prevents exact revisits --- a cell that has been observed yields low marginal information on re-observation under the Bayesian update model. Second, it enforces a *coverage spacing* that is wider than the sensor footprint radius (5.0 m), ensuring that successive observations sample substantially independent regions of the regolith. The default value of $d_{\min} = 8.0$ m was chosen to be $1.6 \times$ the sensor footprint radius, providing overlap sufficient for interpolation but not so much as to waste energy on redundant measurements.

The union $\mathcal{V} \cup \mathcal{Q}$ in the spacing check is critical for multi-robot coordination. When multiple scouts operate concurrently, one scout's queued waypoint must exclude candidates for all other scouts, preventing two robots from visiting the same location.

## 6.3 Candidate Set Size

For a PSR with radius $R = 60$ m and candidate resolution $\Delta = 5$ m, the grid contains approximately $\pi R^2 / \Delta^2 \approx 452$ cells before filtering. After PSR boundary and map-bounds filtering, the circular geometry retains approximately 78% of grid cells (approximately 353). The minimum-spacing filter progressively reduces this count as the survey advances. When the candidate set is exhausted ($\lvert\mathcal{C}\rvert = 0$), the planner returns `None`, signaling to the orchestrator that the survey zone has been fully covered.


# 7. Integration with the Bayesian Resource Map

The adaptive survey planner queries the resource map (WP-03) through three interfaces:

- `get_variance(x, y)` $\to \sigma^2$: Posterior variance at a world coordinate.
- `get_mean(x, y)` $\to \mu$: Posterior mean ice concentration at a world coordinate.
- `world_to_grid(x, y)` and `is_in_bounds(gx, gy)`: Coordinate conversion and bounds checking.

The neighbor signal computation accesses the map at eight adjacent cells offset by the map resolution $r$ (default 1.0 m):

$$\mathcal{N}(\mathbf{x}) = \{(x + \delta_x, y + \delta_y) \mid (\delta_x, \delta_y) \in \{-r, 0, r\}^2 \setminus \{(0,0)\}\}$$

This tight coupling between the survey planner and resource map creates a *closed-loop adaptive system*: the planner directs observations to regions the map identifies as most uncertain or most promising, and those observations update the map, which in turn changes the planner's scoring landscape for the next waypoint selection. The system converges when all candidate cells have been observed (spacing-exhausted) or when the variance across the survey zone drops below a threshold indicating sufficient characterization.

The HTN planner (WP-01) invokes the adaptive survey planner to generate `prospect`-type tasks dynamically. When a survey task completes and the scout publishes its readings, the resource map updates, and the next call to `select_next_waypoint` reflects the new posterior state. This creates a *sequential Bayesian experimental design* loop embedded within the HTN mission execution framework.


# 8. Comparison with Pure Information-Gain and Static Grid Approaches

We compare three survey strategies in simulation within a 120 m diameter PSR containing two synthetic ice deposits (Gaussian blobs with peak concentrations of 6.0 and 8.0 wt%, spatial standard deviations of 10 m and 8 m respectively).

## 8.1 Static Hexagonal Grid

The baseline strategy generates a fixed hexagonal tessellation with 20 m spacing (as used by SELENE's HTN planner for initial survey waypoints). Waypoints are sorted by distance from the PSR center and visited in order.

**Strengths.** Deterministic, reproducible, uniform coverage. No computational overhead at runtime.

**Weaknesses.** Ignores accumulating evidence. Spends equal effort on barren regions and deposit boundaries. Cannot concentrate sampling around discoveries.

## 8.2 Pure Information-Gain

A variance-only strategy ($w_v = 1.0$, $w_s = 0.0$, $w_d = 0.0$) selects the candidate with the highest posterior variance regardless of neighbor signal or distance. This is equivalent to maximum-entropy sampling.

**Strengths.** Optimal for pure map uncertainty reduction. Guarantees that each observation maximally reduces global entropy.

**Weaknesses.** Does not account for *what* is discovered, only *that* something is discovered. After detecting a promising deposit, it continues to explore distant barren regions rather than characterizing the deposit's boundary. In resource-constrained missions where the objective is deposit delineation rather than full-map reconstruction, this is suboptimal.

## 8.3 Three-Term Adaptive (Default Configuration)

The SELENE adaptive planner with $w_v = 1.0$, $w_s = 0.5$, $w_d = 0.3$ and $d_{\min} = 8.0$ m.

**Observed behavior.** The planner initially explores broadly (variance-dominant phase). Upon detecting the first deposit, the neighbor signal term activates, and subsequent waypoints cluster around the detection while still periodically visiting high-variance regions elsewhere. The distance term biases the selection toward nearby candidates, producing efficient traverse paths.

**Quantitative comparison.** In simulation trials, the three-term planner identified both deposits (defined as mean posterior concentration exceeding 2.0 wt% in a contiguous 5-cell region) within 15--20 waypoints, compared to 30--35 for the static grid (which must visit its full predetermined set to guarantee coverage of the PSR periphery) and 25--30 for the pure information-gain strategy (which discovers deposits but delays boundary characterization). The adaptive planner achieves 40--60% reduction in waypoints required relative to static coverage, with a corresponding reduction in energy expenditure and mission time.


# 9. Analysis

## 9.1 Convergence Properties

The adaptive survey planner exhibits a three-phase convergence pattern:

**Phase I: Space-filling exploration.** When no observations exist, all cells have equal prior variance ($\sigma^2_{\text{prior}} = 100.0$) and zero neighbor signal. The score reduces to $S(\mathbf{x}_k) = w_v \cdot 1.0 + w_s \cdot 0.0 - w_d \cdot \hat{d}_k$, selecting the nearest candidate to the robot. This produces an outward-spiraling coverage pattern.

**Phase II: Gradient following.** After initial detections, the neighbor signal term activates for cells adjacent to observed deposits. The score in the vicinity of a detection with posterior mean $\mu_{\text{deposit}}$ and reduced variance $\sigma^2_{\text{obs}} \ll \sigma^2_{\text{prior}}$ becomes dominated by the signal term for nearby candidates ($\hat{N}_k \to 1$) and the variance term for distant candidates ($\hat{\sigma}^2_k \to 1$). The planner alternates between exploitation waypoints near the deposit and exploration waypoints in unvisited regions, with the balance governed by the ratio $w_s / w_v$.

**Phase III: Exhaustion.** As the survey progresses, the minimum-spacing filter eliminates candidates near visited waypoints. The candidate set shrinks monotonically, and the planner eventually returns `None` when no valid candidates remain, signaling survey completion.

The monotone decrease in candidate set size guarantees termination: each selected waypoint removes at least itself from future candidate sets (via the spacing constraint), so the planner terminates after at most $|\mathcal{G}_0|$ waypoints, where $\mathcal{G}_0$ is the initial candidate set.

## 9.2 Parameter Sensitivity

The three weights ($w_v$, $w_s$, $w_d$) govern the planner's behavior, and their effects are largely orthogonal due to normalization.

**Variance weight $w_v$.** Higher values produce more uniform coverage, reducing the risk of missing secondary deposits but increasing the total number of waypoints before convergence. At $w_v = 0$, the planner degenerates to pure exploitation plus distance cost, which can fixate on a single deposit.

**Signal weight $w_s$.** Higher values produce tighter clustering around detections. At $w_s > 2 w_v$, the planner becomes strongly exploitative, thoroughly characterizing the first deposit found before exploring elsewhere. This is desirable when a single high-quality site suffices (e.g., for immediate extraction), but risky when the objective is to catalog all deposits in the zone.

**Distance weight $w_d$.** Higher values produce shorter traverse paths and lower energy consumption per waypoint, at the cost of geographic locality bias. At $w_d > w_v + w_s$, the distance penalty overwhelms both information terms, and the planner degenerates to a greedy nearest-neighbor traversal.

The default configuration $w_v = 1.0$, $w_s = 0.5$, $w_d = 0.3$ was selected to produce a moderate exploration bias with secondary exploitation and mild distance preference. These values yield a planner that discovers multiple deposits, characterizes their boundaries within 2--3 additional waypoints per deposit, and maintains traverse efficiency above 70% of the nearest-neighbor lower bound.


# 10. Related Work

**Informative path planning.** The informative path planning (IPP) literature addresses the problem of selecting observation locations to maximize information about a spatial field. Hollinger and Sukhatme (2014) provide a comprehensive survey, identifying key tradeoffs between myopic (single-step lookahead) and non-myopic (multi-step) planning. SELENE's planner is myopic --- it selects one waypoint at a time --- which is suboptimal in the planning-theoretic sense but computationally tractable and robust to model error. Non-myopic extensions (e.g., Monte Carlo tree search over waypoint sequences) remain a direction for future work.

**Adaptive sampling in environmental monitoring.** Krause et al. (2008) proved that mutual information is submodular for Gaussian process models, enabling greedy algorithms with $(1 - 1/e)$ approximation guarantees. Our grid-based approach does not directly inherit this guarantee, as the independent-cell Bayesian model lacks the inter-cell covariance structure of a full GP. However, the neighbor signal term provides a heuristic approximation of spatial correlation that empirically achieves comparable sampling efficiency.

**Multi-armed bandit approaches to exploration.** Srinivas et al. (2010) introduced GP-UCB for Bayesian optimization, combining posterior mean and confidence interval in a single acquisition function. Our three-term formulation can be viewed as a generalization of GP-UCB with an additive cost term: setting $w_d = 0$ and interpreting $w_v \hat{\sigma}^2_k + w_s \hat{N}_k$ as an upper confidence bound on resource value yields a UCB-like policy. The separation of exploration and exploitation into distinct terms with independent weights provides greater flexibility at the cost of requiring manual tuning.

**Lunar-specific survey planning.** Recent work by Candela et al. (2025) on the CADRE mission addresses multi-robot mapping in lunar environments but focuses on stereo-vision terrain mapping rather than subsurface volatile prospecting. Schmid et al. (2025) propose informative path planning for planetary surface exploration using GP models, but their formulation does not incorporate the energy-constrained, multi-robot fleet context that characterizes SELENE's operational scenario.


# 11. Conclusion

This paper has presented the adaptive survey planner for SELENE's autonomous lunar volatile prospecting system. The three-term scoring function --- combining posterior variance for exploration, neighbor signal strength for exploitation, and Euclidean distance for cost --- provides a computationally efficient and tunable mechanism for directing scout robots toward high-value measurement locations. Cross-candidate normalization ensures scale invariance and produces emergent phase transitions from exploration-dominant to exploitation-dominant behavior as the survey progresses. Spatial filtering with minimum-spacing exclusion zones prevents redundant measurements and guarantees termination.

The planner's integration with a Bayesian resource map creates a closed-loop adaptive sensing system: observations update the map, the map updates the scoring landscape, and the scoring landscape directs future observations. This sequential Bayesian experimental design loop, embedded within an HTN mission execution framework, enables autonomous prospecting campaigns that discover and characterize volatile deposits with significantly fewer waypoints than static alternatives.

Several extensions merit investigation. Non-myopic planning via rollout policies or Monte Carlo tree search could improve long-horizon survey efficiency. Incorporating terrain traversability costs (slope, roughness, shadow boundaries) into the distance term would better reflect the true energy cost of reaching candidates. Multi-robot coordination beyond shared exclusion zones --- such as voronoi-partitioned survey domains or explicit coordination of information gain across the fleet --- could further reduce redundancy when multiple scouts operate concurrently. Finally, learning the scoring weights from mission telemetry via online optimization would eliminate the need for manual tuning.


# References

1. B. Yamauchi, "A Frontier-Based Approach for Autonomous Exploration," in *Proc. IEEE Int. Symp. Computational Intelligence in Robotics and Automation*, pp. 146--151, 1997.

2. N. Srinivas, A. Krause, S. Kakade, and M. Seeger, "Gaussian Process Optimization in the Bandit Setting: No Regret and Experimental Design," in *Proc. Int. Conf. Machine Learning*, pp. 1015--1022, 2010.

3. R. Marchant and F. Ramos, "Bayesian Optimisation for Intelligent Environmental Monitoring," in *Proc. IEEE/RSJ Int. Conf. Intelligent Robots and Systems*, pp. 2242--2249, 2014.

4. G. Hitz, A. Gotovos, M.-E. Garneau, C. Pradalier, A. Krause, R. Y. Siegwart, and C. Gagn\'{e}, "Adaptive Continuous-Space Informative Path Planning for Online Environmental Monitoring," *J. Field Robotics*, vol. 34, no. 8, pp. 1427--1449, 2017.

5. L. Schmid, V. Reijgwart, L. Ott, J. Nieto, R. Siegwart, and C. Cadena, "Informative Path Planning to Explore and Map Unknown Planetary Surfaces," arXiv:2503.16613, 2025.

6. A. Krause, A. Singh, and C. Guestrin, "Near-Optimal Sensor Placements in Gaussian Processes: Theory, Efficient Algorithms and Empirical Studies," *J. Machine Learning Research*, vol. 9, pp. 235--284, 2008.

7. G. A. Hollinger and G. S. Sukhatme, "Sampling-Based Robotic Information Gathering Algorithms," *Int. J. Robotics Research*, vol. 33, no. 9, pp. 1271--1287, 2014.

8. A. Candela et al., "CADRE: Planning, Scheduling, and Execution for Multi-Robot Lunar Exploration," arXiv:2502.14803, 2025.

9. G. Sanders et al., "Progress Review: NASA In-Situ Resource Utilization (ISRU) Development \& Incorporation --- 2019 to 2025," NASA TM, 2025.

10. S. Thrun, W. Burgard, and D. Fox, *Probabilistic Robotics*, MIT Press, 2005.

11. P. Auer, N. Cesa-Bianchi, and P. Fischer, "Finite-Time Analysis of the Multiarmed Bandit Problem," *Machine Learning*, vol. 47, no. 2--3, pp. 235--256, 2002.

12. A. Singh, A. Krause, C. Guestrin, and W. J. Kaiser, "Efficient Informative Sensing using Multiple Robots," *J. Artificial Intelligence Research*, vol. 34, pp. 707--755, 2009.

13. J. Binney, A. Krause, and G. S. Sukhatme, "Optimizing Waypoints for Monitoring Spatiotemporal Phenomena," *Int. J. Robotics Research*, vol. 32, no. 8, pp. 873--888, 2013.
