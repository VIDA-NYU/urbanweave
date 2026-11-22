July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-8 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.36, businesses 0.33, common places 0.31. Hotels: tax year 2021, weighted by units.

Smoothed POIs: Gaussian kernel over H3 grid distance d ≤ k, σ = k/2, each POI's mass normalized to 1. Bandwidth chosen per layer on January 2013 (January cells rebuilt from January zone totals); blends use the k chosen for the CRIF-weighted combination (k = 4). Smoothed CRIF weights from January: k = 1: hotels 0.38, businesses 0.32, common places 0.30; k = 2: hotels 0.42, businesses 0.30, common places 0.28; k = 3: hotels 0.45, businesses 0.28, common places 0.27; k = 4: hotels 0.47, businesses 0.26, common places 0.27; k = 6: hotels 0.49, businesses 0.24, common places 0.27; k = 8: hotels 0.51, businesses 0.22, common places 0.27.

| method                                                      | area      | wrong cell   |   correlation | busiest 1% error   |    MAE |    RMSE |    R2 |   seconds |
|:------------------------------------------------------------|:----------|:-------------|--------------:|:-------------------|-------:|--------:|------:|----------:|
| areal (no prior)                                            | NYC       | 8.5%         |         0.991 | 7.7%               |  308.5 |  1342.3 | 0.979 |       0.2 |
| areal (no prior)                                            | Manhattan | 5.8%         |         0.99  | 7.6%               | 2647.2 |  4100.6 | 0.976 |       0.2 |
| hotels                                                      | NYC       | 18.6%        |         0.94  | 18.5%              |  678.5 |  3407.2 | 0.868 |       0.3 |
| hotels                                                      | Manhattan | 16.2%        |         0.906 | 17.1%              | 7431   | 12274.6 | 0.787 |       0.3 |
| businesses                                                  | NYC       | 11.2%        |         0.974 | 11.4%              |  406.7 |  2168.5 | 0.946 |       0.5 |
| businesses                                                  | Manhattan | 8.5%         |         0.968 | 5.3%               | 3909.7 |  6800.3 | 0.935 |       0.5 |
| common places                                               | NYC       | 12.3%        |         0.973 | 15.2%              |  446.8 |  2174.6 | 0.946 |       0.4 |
| common places                                               | Manhattan | 10.0%        |         0.959 | 15.6%              | 4582.9 |  7595.1 | 0.918 |       0.4 |
| POIs, equal weights                                         | NYC       | 10.7%        |         0.979 | 9.8%               |  391.6 |  1951.1 | 0.957 |       1   |
| POIs, equal weights                                         | Manhattan | 8.6%         |         0.968 | 9.4%               | 3974.1 |  6746.1 | 0.936 |       1   |
| POIs, CRIF weights (min-max)                                | NYC       | 9.9%         |         0.981 | 11.1%              |  361.1 |  1846.8 | 0.961 |       0.8 |
| POIs, CRIF weights (min-max)                                | Manhattan | 7.7%         |         0.972 | 4.6%               | 3558.2 |  6333.9 | 0.943 |       0.8 |
| historical (Jan 2013)                                       | NYC       | 2.1%         |         0.999 | 1.6%               |   75.4 |   529.2 | 0.997 |      10.3 |
| historical (Jan 2013)                                       | Manhattan | 1.9%         |         0.998 | 2.5%               |  870.2 |  1926.4 | 0.995 |      10.3 |
| blend, α = 0.5                                              | NYC       | 4.1%         |         0.997 | 3.2%               |  149.3 |   794.1 | 0.993 |      11.6 |
| blend, α = 0.5                                              | Manhattan | 3.5%         |         0.994 | 3.1%               | 1616.5 |  2892.7 | 0.988 |      11.6 |
| blend, α = 0.75                                             | NYC       | 2.9%         |         0.998 | 2.1%               |  105.4 |   603.4 | 0.996 |      10.9 |
| blend, α = 0.75                                             | Manhattan | 2.4%         |         0.997 | 2.7%               | 1126.5 |  2195.7 | 0.993 |      10.9 |
| blend, α = 0.9                                              | NYC       | 2.3%         |         0.999 | 1.7%               |   82.8 |   532.2 | 0.997 |      12.3 |
| blend, α = 0.9                                              | Manhattan | 2.0%         |         0.998 | 2.6%               |  897.7 |  1936.3 | 0.995 |      12.3 |
| hotels, smoothed k = 1                                      | NYC       | 18.2%        |         0.939 | 19.8%              |  665.2 |  3571.8 | 0.855 |       0.2 |
| hotels, smoothed k = 1                                      | Manhattan | 15.7%        |         0.911 | 9.4%               | 7217   | 12753.1 | 0.77  |       0.2 |
| businesses, smoothed k = 1                                  | NYC       | 9.9%         |         0.979 | 10.6%              |  360.7 |  1974.4 | 0.956 |       0.2 |
| businesses, smoothed k = 1                                  | Manhattan | 7.0%         |         0.971 | 0.8%               | 3226.8 |  6554.8 | 0.939 |       0.2 |
| common places, smoothed k = 1                               | NYC       | 10.7%        |         0.982 | 12.3%              |  391.1 |  1785.9 | 0.964 |       0.2 |
| common places, smoothed k = 1                               | Manhattan | 7.8%         |         0.975 | 10.5%              | 3602.3 |  5885.3 | 0.951 |       0.2 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | NYC       | 9.8%         |         0.985 | 9.4%               |  355.9 |  1654.3 | 0.969 |       0.2 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | Manhattan | 6.9%         |         0.981 | 4.8%               | 3151.5 |  5316.9 | 0.96  |       0.2 |
| hotels, smoothed k = 2                                      | NYC       | 12.3%        |         0.977 | 12.6%              |  450.2 |  2054.4 | 0.952 |       0.2 |
| hotels, smoothed k = 2                                      | Manhattan | 9.4%         |         0.969 | 10.2%              | 4327.6 |  6809.8 | 0.934 |       0.2 |
| businesses, smoothed k = 2 (chosen on Jan)                  | NYC       | 9.2%         |         0.988 | 6.3%               |  334.3 |  1469.6 | 0.975 |       0.2 |
| businesses, smoothed k = 2 (chosen on Jan)                  | Manhattan | 5.9%         |         0.987 | 1.7%               | 2718.1 |  4305.5 | 0.974 |       0.2 |
| common places, smoothed k = 2                               | NYC       | 9.6%         |         0.987 | 7.5%               |  351.9 |  1480.6 | 0.975 |       0.2 |
| common places, smoothed k = 2                               | Manhattan | 6.5%         |         0.986 | 7.8%               | 3007.9 |  4484.7 | 0.972 |       0.2 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | NYC       | 9.5%         |         0.987 | 7.0%               |  345.3 |  1502.9 | 0.974 |       0.2 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | Manhattan | 6.3%         |         0.986 | 6.0%               | 2896.9 |  4538.9 | 0.971 |       0.2 |
| hotels, smoothed k = 3                                      | NYC       | 9.5%         |         0.988 | 7.5%               |  346.1 |  1475.7 | 0.975 |       0.2 |
| hotels, smoothed k = 3                                      | Manhattan | 6.3%         |         0.987 | 8.2%               | 2897.4 |  4367.5 | 0.973 |       0.2 |
| businesses, smoothed k = 3                                  | NYC       | 9.2%         |         0.989 | 6.1%               |  336.6 |  1396.5 | 0.978 |       0.2 |
| businesses, smoothed k = 3                                  | Manhattan | 5.9%         |         0.989 | 4.2%               | 2729.8 |  3988.9 | 0.977 |       0.2 |
| common places, smoothed k = 3                               | NYC       | 9.5%         |         0.988 | 6.8%               |  347   |  1430.8 | 0.977 |       0.2 |
| common places, smoothed k = 3                               | Manhattan | 6.4%         |         0.988 | 6.7%               | 2939   |  4249.1 | 0.974 |       0.2 |
| POIs smoothed k = 3, CRIF weights (min-max)                 | NYC       | 9.2%         |         0.989 | 6.2%               |  335.2 |  1401.3 | 0.978 |       0.2 |
| POIs smoothed k = 3, CRIF weights (min-max)                 | Manhattan | 6.0%         |         0.989 | 6.4%               | 2742.4 |  4066.5 | 0.977 |       0.2 |
| hotels, smoothed k = 4 (chosen on Jan)                      | NYC       | 8.9%         |         0.989 | 5.8%               |  324   |  1356.6 | 0.979 |       0.2 |
| hotels, smoothed k = 4 (chosen on Jan)                      | Manhattan | 5.7%         |         0.99  | 7.1%               | 2613.4 |  3885.5 | 0.979 |       0.2 |
| POIs smoothed k = 4, CRIF weights (min-max) (chosen on Jan) | NYC       | 9.1%         |         0.989 | 6.2%               |  331.7 |  1369.8 | 0.979 |       0.2 |
| POIs smoothed k = 4, CRIF weights (min-max) (chosen on Jan) | Manhattan | 5.9%         |         0.989 | 6.6%               | 2720.4 |  3973.8 | 0.978 |       0.2 |
| common places, smoothed k = 8 (chosen on Jan)               | NYC       | 9.4%         |         0.989 | 6.9%               |  343.9 |  1421.1 | 0.977 |       0.2 |
| common places, smoothed k = 8 (chosen on Jan)               | Manhattan | 6.4%         |         0.988 | 7.6%               | 2967.2 |  4303.4 | 0.974 |       0.2 |
| blend, smoothed POIs k = 4, α = 0.5                         | NYC       | 3.8%         |         0.998 | 2.0%               |  138.6 |   612.8 | 0.996 |      10.9 |
| blend, smoothed POIs k = 4, α = 0.5                         | Manhattan | 2.7%         |         0.997 | 3.7%               | 1221.5 |  2100.7 | 0.994 |      10.9 |
| blend, smoothed POIs k = 4, α = 0.75                        | NYC       | 2.9%         |         0.998 | 1.5%               |  104   |   538.4 | 0.997 |      11.2 |
| blend, smoothed POIs k = 4, α = 0.75                        | Manhattan | 2.1%         |         0.998 | 3.0%               |  972.5 |  1916.9 | 0.995 |      11.2 |
| blend, smoothed POIs k = 4, α = 0.9                         | NYC       | 2.4%         |         0.999 | 1.4%               |   86   |   525.5 | 0.997 |      10.7 |
| blend, smoothed POIs k = 4, α = 0.9                         | Manhattan | 1.9%         |         0.998 | 2.7%               |  869.8 |  1901.6 | 0.995 |      10.7 |

Bandwidth selection on January (wrong-cell share, NYC, January rebuilt from its own zone totals; k = 0 is the raw count):

| layer                        | k = 0   | k = 1   | k = 2   | k = 3   | k = 4   | k = 6   | k = 8   |
|:-----------------------------|:--------|:--------|:--------|:--------|:--------|:--------|:--------|
| POIs, CRIF weights (min-max) | 11.3%   | 9.6%    | 8.9%    | 8.9%    | 8.8%    | 8.8%    | 8.8%    |
| businesses                   | 11.9%   | 9.6%    | 8.8%    | 8.9%    | 8.9%    | 8.9%    | 9.0%    |
| common places                | 13.0%   | 10.4%   | 9.3%    | 9.2%    | 9.1%    | 9.0%    | 9.0%    |
| hotels                       | 26.5%   | 18.5%   | 11.9%   | 9.0%    | 8.5%    | 8.6%    | 8.7%    |
