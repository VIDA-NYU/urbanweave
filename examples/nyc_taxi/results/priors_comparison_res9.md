July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-9 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.26, businesses 0.38, common places 0.36. Hotels: tax year 2021, weighted by units.

| method                       | area      | wrong cell   |   correlation | busiest 1% error   |    MAE |   RMSE |     R2 |   seconds |
|:-----------------------------|:----------|:-------------|--------------:|:-------------------|-------:|-------:|-------:|----------:|
| areal (no prior)             | NYC       | 19.1%        |         0.929 | 25.3%              |  100.9 |  549   |  0.862 |       0.4 |
| areal (no prior)             | Manhattan | 15.4%        |         0.913 | 32.8%              | 1008.1 | 1759.6 |  0.832 |       0.4 |
| hotels                       | NYC       | 46.6%        |         0.657 | 72.0%              |  246.6 | 1538.6 | -0.082 |       0.9 |
| hotels                       | Manhattan | 44.2%        |         0.572 | 62.5%              | 2886.5 | 5537.1 | -0.66  |       0.9 |
| businesses                   | NYC       | 24.6%        |         0.79  | 43.1%              |  130.2 | 1024.9 |  0.52  |       0.9 |
| businesses                   | Manhattan | 21.3%        |         0.762 | 37.0%              | 1390.9 | 3173.8 |  0.455 |       0.9 |
| common places                | NYC       | 25.7%        |         0.862 | 32.2%              |  136.3 |  774.3 |  0.726 |       0.6 |
| common places                | Manhattan | 23.2%        |         0.804 | 24.7%              | 1513   | 2687.9 |  0.609 |       0.6 |
| POIs, equal weights          | NYC       | 28.5%        |         0.799 | 50.0%              |  150.9 | 1001.4 |  0.542 |       0.9 |
| POIs, equal weights          | Manhattan | 26.4%        |         0.725 | 41.9%              | 1726.8 | 3545.6 |  0.319 |       0.9 |
| POIs, CRIF weights (min-max) | NYC       | 23.1%        |         0.878 | 33.5%              |  122.2 |  724.5 |  0.76  |       1   |
| POIs, CRIF weights (min-max) | Manhattan | 20.5%        |         0.829 | 27.3%              | 1342.7 | 2494.6 |  0.663 |       1   |
| historical (Jan 2013)        | NYC       | 2.9%         |         0.998 | 3.2%               |   15.4 |   87.6 |  0.996 |      10.2 |
| historical (Jan 2013)        | Manhattan | 2.5%         |         0.998 | 3.0%               |  163.5 |  287.6 |  0.996 |      10.2 |
| blend, α = 0.5               | NYC       | 8.7%         |         0.972 | 13.1%              |   46.2 |  351.6 |  0.944 |      11.9 |
| blend, α = 0.5               | Manhattan | 7.9%         |         0.957 | 5.6%               |  516.2 | 1273.9 |  0.912 |      11.9 |
| blend, α = 0.75              | NYC       | 5.5%         |         0.99  | 7.4%               |   29   |  205.8 |  0.981 |      12.9 |
| blend, α = 0.75              | Manhattan | 4.8%         |         0.985 | 3.0%               |  311.3 |  736.6 |  0.971 |      12.9 |
| blend, α = 0.9               | NYC       | 3.8%         |         0.997 | 4.8%               |   20.4 |  121.6 |  0.993 |      17.8 |
| blend, α = 0.9               | Manhattan | 3.3%         |         0.995 | 3.0%               |  214.7 |  420.9 |  0.99  |      17.8 |
