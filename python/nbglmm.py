"""
Negative binomial (NB2) mixed model with a random intercept per participant.

    y_ij ~ NB(mu_ij, alpha)
    log mu_ij = x_ij' beta + log(hours_ij) + u_i,   u_i ~ N(0, sigma^2)

The random intercept is integrated out with Gauss-Hermite quadrature and the
marginal likelihood is maximised with L-BFGS. Standard errors come from a
finite-difference Hessian at the optimum.

statsmodels doesn't have a frequentist NB GLMM, and this model is small enough
(a handful of fixed effects, one variance component) that doing it directly is
simpler than pulling in R.
"""

from dataclasses import dataclass

import numpy as np
from scipy import optimize, special


@dataclass
class Fit:
    names: list
    beta: np.ndarray
    se: np.ndarray
    alpha: float
    sigma: float
    loglik: float
    converged: bool

    def rate_ratio(self, name):
        k = self.names.index(name)
        b, s = self.beta[k], self.se[k]
        return np.exp(b), np.exp(b - 1.96 * s), np.exp(b + 1.96 * s)

    def summary(self):
        rows = [f"{'term':<22}{'coef':>9}{'se':>9}{'RR':>9}{'2.5%':>9}{'97.5%':>9}"]
        for n, b, s in zip(self.names, self.beta, self.se):
            rows.append(f"{n:<22}{b:9.3f}{s:9.3f}{np.exp(b):9.3f}"
                        f"{np.exp(b - 1.96 * s):9.3f}{np.exp(b + 1.96 * s):9.3f}")
        rows.append(f"alpha (NB dispersion) = {self.alpha:.3f}")
        rows.append(f"sigma (participant SD, log scale) = {self.sigma:.3f}")
        rows.append(f"log-likelihood = {self.loglik:.1f}   converged = {self.converged}")
        return "\n".join(rows)


class NBGLMM:
    def __init__(self, y, X, offset, groups, names, n_quad=25):
        order = np.argsort(groups, kind="stable")
        self.y = np.asarray(y, float)[order]
        self.X = np.asarray(X, float)[order]
        self.off = np.asarray(offset, float)[order]
        g = np.asarray(groups)[order]
        _, self.starts = np.unique(g, return_index=True)
        self.names = list(names)
        nodes, weights = np.polynomial.hermite.hermgauss(n_quad)
        self.nodes = np.sqrt(2) * nodes
        self.logw = np.log(weights / np.sqrt(np.pi))
        self.lgy1 = special.gammaln(self.y + 1)

    def _unpack(self, theta):
        p = self.X.shape[1]
        return theta[:p], np.exp(theta[p]), np.exp(theta[p + 1])

    def negloglik(self, theta):
        beta, alpha, sigma = self._unpack(theta)
        r = 1.0 / alpha
        eta = (self.X @ beta + self.off)[:, None] + sigma * self.nodes[None, :]
        mu = np.exp(eta)
        ll = (special.gammaln(self.y[:, None] + r) - special.gammaln(r) - self.lgy1[:, None]
              + r * np.log(r / (r + mu)) + self.y[:, None] * np.log(mu / (r + mu)))
        per_group = np.add.reduceat(ll, self.starts, axis=0)       # groups x nodes
        return -special.logsumexp(per_group + self.logw[None, :], axis=1).sum()

    def fit(self, start=None):
        p = self.X.shape[1]
        if start is None:
            start = np.zeros(p + 2)
            start[0] = np.log(max(self.y.mean(), 1e-3)) - self.off.mean()
            start[p], start[p + 1] = np.log(0.5), np.log(0.5)
        res = optimize.minimize(self.negloglik, start, method="L-BFGS-B")
        beta, alpha, sigma = self._unpack(res.x)
        se = np.sqrt(np.diag(np.linalg.inv(self._hessian(res.x))))[:p]
        return Fit(self.names, beta, se, alpha, sigma, -res.fun, bool(res.success)), res.x

    def fit_point(self, start):
        """Point estimate only (no Hessian), for the many leave-one-out refits."""
        res = optimize.minimize(self.negloglik, start, method="L-BFGS-B")
        return res.x

    def _hessian(self, x, h=1e-4):
        k = len(x)
        H = np.zeros((k, k))
        f0 = self.negloglik(x)
        for i in range(k):
            for j in range(i, k):
                ei, ej = np.eye(k)[i] * h, np.eye(k)[j] * h
                if i == j:
                    H[i, i] = (self.negloglik(x + ei) - 2 * f0 + self.negloglik(x - ei)) / h**2
                else:
                    H[i, j] = H[j, i] = (self.negloglik(x + ei + ej) - self.negloglik(x + ei - ej)
                                         - self.negloglik(x - ei + ej) + self.negloglik(x - ei - ej)) / (4 * h**2)
        return H


def design(df):
    """Fixed effects: age group, bedtime (centred), season (winter = reference)."""
    X = np.column_stack([
        np.ones(len(df)),
        (df["age_group"] == "45-55").astype(float),
        df["bedtime_h"] - 5.5,
        (df["season"] == "spring").astype(float),
        (df["season"] == "summer").astype(float),
        (df["season"] == "autumn").astype(float),
    ])
    names = ["intercept", "age 45-55", "bedtime (h, c.)", "spring", "summer", "autumn"]
    return X, names


def model_for(df, n_quad=25):
    X, names = design(df)
    return NBGLMM(df["n_events"].values, X, np.log(df["hours_slept"].values),
                  df["participant_id"].values, names, n_quad=n_quad)
