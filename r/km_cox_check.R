# Independent cross-check of the Python survival estimates with R's survival package.
# Input:  r/input/survival_data.csv, written by `python -m src.models export`
#         (one row per policy: duration observed, lapse flag, Cox design matrix).
# Output: r/output/km_check.csv and r/output/cox_check.csv, committed and read by the app.
# Run from the repository root: Rscript r/km_cox_check.R

suppressPackageStartupMessages(library(survival))

dat <- read.csv("r/input/survival_data.csv", stringsAsFactors = FALSE)

# Kaplan-Meier, overall and by income type. conf.type = "log-log" matches lifelines'
# exponential Greenwood intervals.
km_rows <- function(fit, group) {
  s <- summary(fit, times = 1:10, extend = TRUE)
  data.frame(group = group, duration = s$time, persistency = s$surv,
             lower_95 = s$lower, upper_95 = s$upper)
}
km_all <- km_rows(survfit(Surv(duration, lapsed) ~ 1, data = dat, conf.type = "log-log"), "All")
km_grp <- do.call(rbind, lapply(sort(unique(dat$income_type)), function(g) {
  km_rows(survfit(Surv(duration, lapsed) ~ 1, data = dat[dat$income_type == g, ], conf.type = "log-log"), g)
}))
write.csv(rbind(km_all, km_grp), "r/output/km_check.csv", row.names = FALSE)

# Cox proportional hazards with the same design matrix, Efron ties (as lifelines) and Breslow for comparison.
covs <- setdiff(names(dat), c("income_type", "duration", "lapsed"))
f <- as.formula(paste("Surv(duration, lapsed) ~", paste(covs, collapse = " + ")))
fit_e <- coxph(f, data = dat, ties = "efron")
fit_b <- coxph(f, data = dat, ties = "breslow")
se <- summary(fit_e)$coefficients
ci <- summary(fit_e)$conf.int
cox <- data.frame(
  term = rownames(se),
  coef = se[, "coef"],
  se = se[, "se(coef)"],
  hazard_ratio = ci[, "exp(coef)"],
  hr_lower_95 = ci[, "lower .95"],
  hr_upper_95 = ci[, "upper .95"],
  p_value = se[, "Pr(>|z|)"],
  coef_breslow = unname(coef(fit_b))
)
write.csv(cox, "r/output/cox_check.csv", row.names = FALSE)

# Proportional hazards check (Schoenfeld residuals, rank time scale, as in the Python test).
zph <- cox.zph(fit_e, transform = "rank", terms = FALSE)
ph <- data.frame(term = rownames(zph$table), chi_square = zph$table[, "chisq"], p_value = zph$table[, "p"])
write.csv(ph, "r/output/ph_check.csv", row.names = FALSE)

cat("R", R.version$major, ".", R.version$minor, " survival ", as.character(packageVersion("survival")), "\n", sep = "")
cat("Wrote r/output/km_check.csv, r/output/cox_check.csv, r/output/ph_check.csv\n")
