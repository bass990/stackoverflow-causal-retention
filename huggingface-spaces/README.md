---
title: Stack Overflow Retention Causal Study
emoji: 📊
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: Does a fast first answer keep new SO contributors? 1.77M users
---

# Stack Overflow new-contributor retention

Interactive results of a causal-inference study on 1.77M new Stack Overflow contributors
(January 2018 to September 2022, BigQuery public dataset). Four estimators, robustness
checks, heterogeneity cuts and a predictive-model ladder, all read from small committed
summary tables. The Space runs the repo's own Dockerfile.

Source, SQL pipeline, notebooks and tests:
[github.com/bass990/stackoverflow-causal-retention](https://github.com/bass990/stackoverflow-causal-retention)
