July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-9 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.26, businesses 0.38, common places 0.36. Hotels: tax year 2021, weighted by units.

Smoothed POIs: Gaussian kernel over H3 grid distance d ≤ k, σ = k/2, each POI's mass normalized to 1. Bandwidth chosen per layer on January 2013 (January cells rebuilt from January zone totals); blends use the k chosen for the CRIF-weighted combination (k = 3). Smoothed CRIF weights from January: k = 1: hotels 0.30, businesses 0.36, common places 0.33; k = 2: hotels 0.35, businesses 0.34, common places 0.31; k = 3: hotels 0.38, businesses 0.33, common places 0.30; k = 4: hotels 0.39, businesses 0.32, common places 0.29; k = 6: hotels 0.42, businesses 0.30, common places 0.28; k = 8: hotels 0.44, businesses 0.28, common places 0.27.

| method                                                      | area      | wrong cell   |   correlation | busiest 1% error   |    MAE |   RMSE |     R2 |   seconds |
|:------------------------------------------------------------|:----------|:-------------|--------------:|:-------------------|-------:|-------:|-------:|----------:|
| areal (no prior)                                            | NYC       | 19.1%        |         0.929 | 25.3%              |  100.9 |  549   |  0.862 |       0.4 |
| areal (no prior)                                            | Manhattan | 15.4%        |         0.913 | 32.8%              | 1008.1 | 1759.6 |  0.832 |       0.4 |
| hotels                                                      | NYC       | 46.6%        |         0.657 | 72.0%              |  246.6 | 1538.6 | -0.082 |       0.6 |
| hotels                                                      | Manhattan | 44.2%        |         0.572 | 62.5%              | 2886.5 | 5537.1 | -0.66  |       0.6 |
| businesses                                                  | NYC       | 24.6%        |         0.79  | 43.1%              |  130.2 | 1024.9 |  0.52  |       0.8 |
| businesses                                                  | Manhattan | 21.3%        |         0.762 | 37.0%              | 1390.9 | 3173.8 |  0.455 |       0.8 |
| common places                                               | NYC       | 25.7%        |         0.862 | 32.2%              |  136.3 |  774.3 |  0.726 |       0.8 |
| common places                                               | Manhattan | 23.2%        |         0.804 | 24.7%              | 1513   | 2687.9 |  0.609 |       0.8 |
| POIs, equal weights                                         | NYC       | 28.5%        |         0.799 | 50.0%              |  150.9 | 1001.4 |  0.542 |       1.2 |
| POIs, equal weights                                         | Manhattan | 26.4%        |         0.725 | 41.9%              | 1726.8 | 3545.6 |  0.319 |       1.2 |
| POIs, CRIF weights (min-max)                                | NYC       | 23.1%        |         0.878 | 33.5%              |  122.2 |  724.5 |  0.76  |       1.2 |
| POIs, CRIF weights (min-max)                                | Manhattan | 20.5%        |         0.829 | 27.3%              | 1342.7 | 2494.6 |  0.663 |       1.2 |
| historical (Jan 2013)                                       | NYC       | 2.9%         |         0.998 | 3.2%               |   15.4 |   87.6 |  0.996 |      11.2 |
| historical (Jan 2013)                                       | Manhattan | 2.5%         |         0.998 | 3.0%               |  163.5 |  287.6 |  0.996 |      11.2 |
| blend, α = 0.5                                              | NYC       | 8.7%         |         0.972 | 13.1%              |   46.2 |  351.6 |  0.944 |      11.6 |
| blend, α = 0.5                                              | Manhattan | 7.9%         |         0.957 | 5.6%               |  516.2 | 1273.9 |  0.912 |      11.6 |
| blend, α = 0.75                                             | NYC       | 5.5%         |         0.99  | 7.4%               |   29   |  205.8 |  0.981 |      12.7 |
| blend, α = 0.75                                             | Manhattan | 4.8%         |         0.985 | 3.0%               |  311.3 |  736.6 |  0.971 |      12.7 |
| blend, α = 0.9                                              | NYC       | 3.8%         |         0.997 | 4.8%               |   20.4 |  121.6 |  0.993 |      12   |
| blend, α = 0.9                                              | Manhattan | 3.3%         |         0.995 | 3.0%               |  214.7 |  420.9 |  0.99  |      12   |
| hotels, smoothed k = 1                                      | NYC       | 37.5%        |         0.725 | 56.9%              |  198.4 | 1289.5 |  0.24  |       0.5 |
| hotels, smoothed k = 1                                      | Manhattan | 34.5%        |         0.655 | 46.3%              | 2255.1 | 4543.4 | -0.118 |       0.5 |
| businesses, smoothed k = 1                                  | NYC       | 20.0%        |         0.89  | 32.0%              |  105.8 |  688.9 |  0.783 |       0.5 |
| businesses, smoothed k = 1                                  | Manhattan | 16.7%        |         0.86  | 37.4%              | 1091.5 | 2272.9 |  0.72  |       0.5 |
| common places, smoothed k = 1                               | NYC       | 21.3%        |         0.909 | 27.4%              |  112.6 |  618.9 |  0.825 |       0.5 |
| common places, smoothed k = 1                               | Manhattan | 18.3%        |         0.876 | 22.2%              | 1196.6 | 2087.8 |  0.764 |       0.5 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | NYC       | 20.4%        |         0.911 | 28.5%              |  108   |  613.8 |  0.828 |       0.6 |
| POIs smoothed k = 1, CRIF weights (min-max)                 | Manhattan | 17.4%        |         0.88  | 30.0%              | 1140   | 2061   |  0.77  |       0.6 |
| hotels, smoothed k = 2                                      | NYC       | 30.3%        |         0.83  | 39.2%              |  160.5 |  909.6 |  0.622 |       0.6 |
| hotels, smoothed k = 2                                      | Manhattan | 27.4%        |         0.776 | 34.6%              | 1788.8 | 3157.8 |  0.46  |       0.6 |
| businesses, smoothed k = 2                                  | NYC       | 18.6%        |         0.929 | 24.9%              |   98.2 |  548.9 |  0.862 |       0.6 |
| businesses, smoothed k = 2                                  | Manhattan | 15.1%        |         0.914 | 30.2%              |  988.6 | 1749.1 |  0.834 |       0.6 |
| common places, smoothed k = 2                               | NYC       | 20.1%        |         0.925 | 26.3%              |  106.2 |  562.6 |  0.855 |       0.6 |
| common places, smoothed k = 2                               | Manhattan | 16.7%        |         0.904 | 26.1%              | 1094   | 1836.6 |  0.817 |       0.6 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | NYC       | 19.4%        |         0.929 | 24.7%              |  102.6 |  547.9 |  0.863 |       0.7 |
| POIs smoothed k = 2, CRIF weights (min-max)                 | Manhattan | 16.1%        |         0.911 | 29.5%              | 1048.8 | 1772.1 |  0.83  |       0.7 |
| hotels, smoothed k = 3                                      | NYC       | 26.5%        |         0.87  | 30.1%              |  140.1 |  762.1 |  0.735 |       0.6 |
| hotels, smoothed k = 3                                      | Manhattan | 23.3%        |         0.826 | 29.8%              | 1524.9 | 2603.2 |  0.633 |       0.6 |
| businesses, smoothed k = 3 (chosen on Jan)                  | NYC       | 18.4%        |         0.933 | 23.3%              |   97.2 |  532.6 |  0.87  |       0.6 |
| businesses, smoothed k = 3 (chosen on Jan)                  | Manhattan | 14.8%        |         0.92  | 27.7%              |  965.8 | 1679.3 |  0.847 |       0.6 |
| common places, smoothed k = 3                               | NYC       | 19.5%        |         0.93  | 24.9%              |  103.4 |  543.5 |  0.865 |       0.6 |
| common places, smoothed k = 3                               | Manhattan | 16.0%        |         0.914 | 27.4%              | 1045.6 | 1743.7 |  0.835 |       0.6 |
| POIs smoothed k = 3, CRIF weights (min-max) (chosen on Jan) | NYC       | 19.0%        |         0.931 | 22.7%              |  100.6 |  540.1 |  0.867 |       0.6 |
| POIs smoothed k = 3, CRIF weights (min-max) (chosen on Jan) | Manhattan | 15.5%        |         0.916 | 28.4%              | 1010.8 | 1727.2 |  0.838 |       0.6 |
| hotels, smoothed k = 8 (chosen on Jan)                      | NYC       | 19.8%        |         0.925 | 23.9%              |  104.8 |  560.9 |  0.856 |       0.6 |
| hotels, smoothed k = 8 (chosen on Jan)                      | Manhattan | 16.1%        |         0.908 | 30.4%              | 1051.7 | 1804   |  0.824 |       0.6 |
| common places, smoothed k = 8 (chosen on Jan)               | NYC       | 19.4%        |         0.929 | 24.3%              |  102.8 |  549.2 |  0.862 |       0.5 |
| common places, smoothed k = 8 (chosen on Jan)               | Manhattan | 15.7%        |         0.914 | 31.9%              | 1023.3 | 1752   |  0.834 |       0.5 |
| blend, smoothed POIs k = 3, α = 0.5                         | NYC       | 7.3%         |         0.991 | 7.0%               |   38.9 |  197   |  0.982 |      11   |
| blend, smoothed POIs k = 3, α = 0.5                         | Manhattan | 6.3%         |         0.987 | 9.0%               |  410.6 |  694   |  0.974 |      11   |
| blend, smoothed POIs k = 3, α = 0.75                        | NYC       | 4.6%         |         0.997 | 4.3%               |   24.3 |  119.9 |  0.993 |      10.7 |
| blend, smoothed POIs k = 3, α = 0.75                        | Manhattan | 3.7%         |         0.996 | 4.7%               |  245   |  408.5 |  0.991 |      10.7 |
| blend, smoothed POIs k = 3, α = 0.9                         | NYC       | 3.4%         |         0.998 | 3.4%               |   18   |   93.2 |  0.996 |      10.2 |
| blend, smoothed POIs k = 3, α = 0.9                         | Manhattan | 2.8%         |         0.997 | 3.5%               |  182.7 |  308.4 |  0.995 |      10.2 |

Bandwidth selection on January (wrong-cell share, NYC, January rebuilt from its own zone totals; k = 0 is the raw count):

| layer                        | k = 0   | k = 1   | k = 2   | k = 3   | k = 4   | k = 6   | k = 8   |
|:-----------------------------|:--------|:--------|:--------|:--------|:--------|:--------|:--------|
| POIs, CRIF weights (min-max) | 23.8%   | 20.1%   | 18.9%   | 18.5%   | 18.7%   | 18.8%   | 18.8%   |
| businesses                   | 23.5%   | 19.4%   | 17.9%   | 17.7%   | 17.8%   | 18.3%   | 18.6%   |
| common places                | 25.1%   | 21.1%   | 19.6%   | 19.0%   | 18.8%   | 18.8%   | 18.8%   |
| hotels                       | 49.8%   | 38.0%   | 30.5%   | 26.5%   | 23.9%   | 20.1%   | 19.4%   |
