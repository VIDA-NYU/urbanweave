July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-10 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.23, businesses 0.43, common places 0.34. Hotels: tax year 2021, weighted by units.

Smoothed POIs: Gaussian kernel over H3 grid distance d ≤ k, σ = k/2, each POI's mass normalized to 1. Bandwidth chosen per layer on January 2013 (January cells rebuilt from January zone totals); blends use the k chosen for the CRIF-weighted combination (k = 6). Smoothed CRIF weights from January: k = 1: hotels 0.25, businesses 0.40, common places 0.35; k = 2: hotels 0.29, businesses 0.37, common places 0.34; k = 3: hotels 0.32, businesses 0.36, common places 0.32; k = 4: hotels 0.33, businesses 0.35, common places 0.32; k = 6: hotels 0.35, businesses 0.34, common places 0.31; k = 8: hotels 0.37, businesses 0.33, common places 0.30.

| method                                                      | area      | wrong cell   |   correlation | busiest 1% error   |   MAE |   RMSE |     R2 |   seconds |
|:------------------------------------------------------------|:----------|:-------------|--------------:|:-------------------|------:|-------:|-------:|----------:|
| areal (no prior)                                            | NYC       | 35.8%        |         0.736 | 48.3%              |  27.3 |  180.3 |  0.541 |       1.6 |
| areal (no prior)                                            | Manhattan | 32.6%        |         0.678 | 67.1%              | 308.2 |  603.1 |  0.46  |       1.6 |
| hotels                                                      | NYC       | 75.0%        |         0.305 | 119.2%             |  57.2 |  562.2 | -3.459 |       2.5 |
| hotels                                                      | Manhattan | 74.0%        |         0.251 | 94.5%              | 699.9 | 2043.2 | -5.202 |       2.5 |
| businesses                                                  | NYC       | 44.6%        |         0.445 | 61.4%              |  34   |  345.2 | -0.681 |       2.7 |
| businesses                                                  | Manhattan | 41.6%        |         0.438 | 62.2%              | 393.6 | 1015.7 | -0.533 |       2.7 |
| common places                                               | NYC       | 54.1%        |         0.502 | 68.9%              |  41.2 |  276.3 | -0.077 |       2.8 |
| common places                                               | Manhattan | 52.2%        |         0.385 | 66.2%              | 493.8 |  966   | -0.386 |       2.8 |
| POIs, equal weights                                         | NYC       | 51.3%        |         0.421 | 83.0%              |  39.1 |  375.9 | -0.994 |       3.2 |
| POIs, equal weights                                         | Manhattan | 49.6%        |         0.337 | 85.9%              | 469.8 | 1342.5 | -1.678 |       3.2 |
| POIs, CRIF weights (min-max)                                | NYC       | 45.8%        |         0.57  | 61.0%              |  34.9 |  244.6 |  0.156 |       3.2 |
| POIs, CRIF weights (min-max)                                | Manhattan | 43.6%        |         0.464 | 63.9%              | 412.7 |  843   | -0.056 |       3.2 |
| historical (Jan 2013)                                       | NYC       | 5.1%         |         0.995 | 6.8%               |   3.9 |   27.3 |  0.989 |      12.2 |
| historical (Jan 2013)                                       | Manhattan | 4.5%         |         0.994 | 5.9%               |  42.8 |   91.9 |  0.987 |      12.2 |
| blend, α = 0.5                                              | NYC       | 13.9%        |         0.87  | 21.0%              |  10.6 |  142.3 |  0.714 |      12.2 |
| blend, α = 0.5                                              | Manhattan | 12.8%        |         0.825 | 26.0%              | 121.3 |  520   |  0.598 |      12.2 |
| blend, α = 0.75                                             | NYC       | 8.7%         |         0.954 | 12.6%              |   6.7 |   81.5 |  0.906 |      12.1 |
| blend, α = 0.75                                             | Manhattan | 7.8%         |         0.937 | 14.6%              |  73.3 |  295.9 |  0.87  |      12.1 |
| blend, α = 0.9                                              | NYC       | 6.3%         |         0.986 | 8.7%               |   4.8 |   44.2 |  0.972 |      12.1 |
| blend, α = 0.9                                              | Manhattan | 5.5%         |         0.982 | 9.0%               |  52.4 |  156.9 |  0.963 |      12.1 |
| hotels, smoothed k = 1                                      | NYC       | 58.7%        |         0.402 | 90.3%              |  44.7 |  409.1 | -1.362 |       2.3 |
| hotels, smoothed k = 1                                      | Manhattan | 56.0%        |         0.348 | 82.8%              | 530.3 | 1419.2 | -1.992 |       2.3 |
| businesses, smoothed k = 1                                  | NYC       | 37.3%        |         0.601 | 52.2%              |  28.4 |  235.7 |  0.217 |       2.1 |
| businesses, smoothed k = 1                                  | Manhattan | 34.1%        |         0.549 | 61.3%              | 322.8 |  764.9 |  0.131 |       2.1 |
| common places, smoothed k = 1                               | NYC       | 43.2%        |         0.645 | 57.1%              |  32.9 |  211.8 |  0.367 |       2.1 |
| common places, smoothed k = 1                               | Manhattan | 40.9%        |         0.543 | 63.6%              | 387.1 |  733.9 |  0.2   |       2.1 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | NYC       | 39.6%        |         0.673 | 53.4%              |  30.1 |  201.6 |  0.427 |       2.2 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | Manhattan | 37.2%        |         0.58  | 64.0%              | 352   |  694.1 |  0.284 |       2.2 |
| hotels, smoothed k = 2                                      | NYC       | 49.9%        |         0.494 | 69.8%              |  38   |  302.3 | -0.289 |       1.9 |
| hotels, smoothed k = 2                                      | Manhattan | 47.0%        |         0.421 | 70.3%              | 444.6 | 1040.9 | -0.61  |       1.9 |
| businesses, smoothed k = 2                                  | NYC       | 36.1%        |         0.679 | 50.7%              |  27.5 |  199.6 |  0.438 |       1.9 |
| businesses, smoothed k = 2                                  | Manhattan | 33.0%        |         0.613 | 66.0%              | 312.7 |  666.1 |  0.341 |       1.9 |
| common places, smoothed k = 2                               | NYC       | 37.8%        |         0.717 | 50.4%              |  28.8 |  186.5 |  0.509 |       1.9 |
| common places, smoothed k = 2                               | Manhattan | 35.1%        |         0.642 | 63.2%              | 331.8 |  634.6 |  0.402 |       1.9 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | NYC       | 36.7%        |         0.722 | 49.6%              |  27.9 |  184.6 |  0.519 |       2.1 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | Manhattan | 33.9%        |         0.65  | 64.2%              | 321.2 |  626.6 |  0.417 |       2.1 |
| hotels, smoothed k = 3                                      | NYC       | 47.7%        |         0.525 | 66.4%              |  36.4 |  275.1 | -0.068 |       1.9 |
| hotels, smoothed k = 3                                      | Manhattan | 44.9%        |         0.438 | 68.6%              | 425.3 |  959.8 | -0.369 |       1.9 |
| businesses, smoothed k = 3                                  | NYC       | 35.3%        |         0.713 | 49.0%              |  26.9 |  187.7 |  0.503 |       1.9 |
| businesses, smoothed k = 3                                  | Manhattan | 32.4%        |         0.651 | 65.6%              | 306.5 |  627.6 |  0.415 |       1.9 |
| common places, smoothed k = 3                               | NYC       | 36.7%        |         0.729 | 49.3%              |  27.9 |  182.3 |  0.531 |       1.9 |
| common places, smoothed k = 3                               | Manhattan | 33.8%        |         0.663 | 63.8%              | 319.8 |  615.7 |  0.437 |       1.9 |
| POIs smoothed k = 3, CRIF weights (min-max)                 | NYC       | 35.9%        |         0.734 | 48.7%              |  27.3 |  181   |  0.538 |       2.1 |
| POIs smoothed k = 3, CRIF weights (min-max)                 | Manhattan | 33.0%        |         0.67  | 64.2%              | 312.3 |  609.7 |  0.448 |       2.1 |
| businesses, smoothed k = 6 (chosen on Jan)                  | NYC       | 34.9%        |         0.742 | 47.1%              |  26.6 |  178.7 |  0.55  |       2   |
| businesses, smoothed k = 6 (chosen on Jan)                  | Manhattan | 31.9%        |         0.687 | 64.4%              | 301.9 |  596   |  0.472 |       2   |
| POIs smoothed k = 6, CRIF weights (min-max) (chosen on Jan) | NYC       | 35.4%        |         0.741 | 47.6%              |  27   |  178.8 |  0.549 |       2.1 |
| POIs smoothed k = 6, CRIF weights (min-max) (chosen on Jan) | Manhattan | 32.3%        |         0.684 | 64.3%              | 305.8 |  598.3 |  0.468 |       2.1 |
| hotels, smoothed k = 8 (chosen on Jan)                      | NYC       | 40.2%        |         0.673 | 52.6%              |  30.7 |  201.1 |  0.43  |       1.9 |
| hotels, smoothed k = 8 (chosen on Jan)                      | Manhattan | 37.3%        |         0.592 | 63.5%              | 352.9 |  684.5 |  0.304 |       1.9 |
| common places, smoothed k = 8 (chosen on Jan)               | NYC       | 35.7%        |         0.74  | 47.9%              |  27.2 |  179.2 |  0.547 |       1.9 |
| common places, smoothed k = 8 (chosen on Jan)               | Manhattan | 32.5%        |         0.683 | 65.6%              | 307.9 |  599.3 |  0.466 |       1.9 |
| blend, smoothed POIs k = 6, α = 0.5                         | NYC       | 12.3%        |         0.979 | 13.9%              |   9.4 |   57.4 |  0.954 |      10.1 |
| blend, smoothed POIs k = 6, α = 0.5                         | Manhattan | 11.1%        |         0.973 | 18.8%              | 104.8 |  203.7 |  0.938 |      10.1 |
| blend, smoothed POIs k = 6, α = 0.75                        | NYC       | 7.7%         |         0.991 | 8.6%               |   5.9 |   36.2 |  0.982 |      10.1 |
| blend, smoothed POIs k = 6, α = 0.75                        | Manhattan | 6.7%         |         0.989 | 10.1%              |  63.5 |  125.1 |  0.977 |      10.1 |
| blend, smoothed POIs k = 6, α = 0.9                         | NYC       | 5.8%         |         0.994 | 7.1%               |   4.5 |   29   |  0.988 |       9.9 |
| blend, smoothed POIs k = 6, α = 0.9                         | Manhattan | 5.1%         |         0.993 | 6.9%               |  48   |   98.2 |  0.986 |       9.9 |

Bandwidth selection on January (wrong-cell share, NYC, January rebuilt from its own zone totals; k = 0 is the raw count):

| layer                        | k = 0   | k = 1   | k = 2   | k = 3   | k = 4   | k = 6   | k = 8   |
|:-----------------------------|:--------|:--------|:--------|:--------|:--------|:--------|:--------|
| POIs, CRIF weights (min-max) | 46.0%   | 39.4%   | 36.3%   | 35.5%   | 35.1%   | 34.9%   | 35.0%   |
| businesses                   | 43.3%   | 36.7%   | 35.6%   | 34.8%   | 34.4%   | 34.4%   | 34.5%   |
| common places                | 53.4%   | 43.1%   | 37.5%   | 36.3%   | 35.8%   | 35.4%   | 35.2%   |
| hotels                       | 75.9%   | 59.0%   | 50.2%   | 48.1%   | 46.3%   | 42.2%   | 40.0%   |
