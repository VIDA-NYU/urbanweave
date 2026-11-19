July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-10 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.23, businesses 0.43, common places 0.34. Hotels: tax year 2021, weighted by units.

| method                       | area      | wrong cell   |   correlation | busiest 1% error   |   MAE |   RMSE |     R2 |   seconds |
|:-----------------------------|:----------|:-------------|--------------:|:-------------------|------:|-------:|-------:|----------:|
| areal (no prior)             | NYC       | 35.8%        |         0.736 | 48.3%              |  27.3 |  180.3 |  0.541 |       1.2 |
| areal (no prior)             | Manhattan | 32.6%        |         0.678 | 67.1%              | 308.2 |  603.1 |  0.46  |       1.2 |
| hotels                       | NYC       | 75.0%        |         0.305 | 119.2%             |  57.2 |  562.2 | -3.459 |       2.1 |
| hotels                       | Manhattan | 74.0%        |         0.251 | 94.5%              | 699.9 | 2043.2 | -5.202 |       2.1 |
| businesses                   | NYC       | 44.6%        |         0.445 | 61.4%              |  34   |  345.2 | -0.681 |       2.4 |
| businesses                   | Manhattan | 41.6%        |         0.438 | 62.2%              | 393.6 | 1015.7 | -0.533 |       2.4 |
| common places                | NYC       | 54.1%        |         0.502 | 68.9%              |  41.2 |  276.3 | -0.077 |       2.2 |
| common places                | Manhattan | 52.2%        |         0.385 | 66.2%              | 493.8 |  966   | -0.386 |       2.2 |
| POIs, equal weights          | NYC       | 51.3%        |         0.421 | 83.0%              |  39.1 |  375.9 | -0.994 |       2.6 |
| POIs, equal weights          | Manhattan | 49.6%        |         0.337 | 85.9%              | 469.8 | 1342.5 | -1.678 |       2.6 |
| POIs, CRIF weights (min-max) | NYC       | 45.8%        |         0.57  | 61.0%              |  34.9 |  244.6 |  0.156 |       2.7 |
| POIs, CRIF weights (min-max) | Manhattan | 43.6%        |         0.464 | 63.9%              | 412.7 |  843   | -0.056 |       2.7 |
| historical (Jan 2013)        | NYC       | 5.1%         |         0.995 | 6.8%               |   3.9 |   27.3 |  0.989 |      10.8 |
| historical (Jan 2013)        | Manhattan | 4.5%         |         0.994 | 5.9%               |  42.8 |   91.9 |  0.987 |      10.8 |
| blend, α = 0.5               | NYC       | 13.9%        |         0.87  | 21.0%              |  10.6 |  142.3 |  0.714 |      12.1 |
| blend, α = 0.5               | Manhattan | 12.8%        |         0.825 | 26.0%              | 121.3 |  520   |  0.598 |      12.1 |
| blend, α = 0.75              | NYC       | 8.7%         |         0.954 | 12.6%              |   6.7 |   81.5 |  0.906 |      11.7 |
| blend, α = 0.75              | Manhattan | 7.8%         |         0.937 | 14.6%              |  73.3 |  295.9 |  0.87  |      11.7 |
| blend, α = 0.9               | NYC       | 6.3%         |         0.986 | 8.7%               |   4.8 |   44.2 |  0.972 |      12.1 |
| blend, α = 0.9               | Manhattan | 5.5%         |         0.982 | 9.0%               |  52.4 |  156.9 |  0.963 |      12.1 |
