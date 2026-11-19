July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-8 cell from their taxi-zone counts. CRIF weights from January 2013: hotels 0.36, businesses 0.33, common places 0.31. Hotels: tax year 2021, weighted by units.

| method                       | area      | wrong cell   |   correlation | busiest 1% error   |    MAE |    RMSE |    R2 |   seconds |
|:-----------------------------|:----------|:-------------|--------------:|:-------------------|-------:|--------:|------:|----------:|
| areal (no prior)             | NYC       | 8.5%         |         0.991 | 7.7%               |  308.5 |  1342.3 | 0.979 |       0.2 |
| areal (no prior)             | Manhattan | 5.8%         |         0.99  | 7.6%               | 2647.2 |  4100.6 | 0.976 |       0.2 |
| hotels                       | NYC       | 18.6%        |         0.94  | 18.5%              |  678.5 |  3407.2 | 0.868 |       0.2 |
| hotels                       | Manhattan | 16.2%        |         0.906 | 17.1%              | 7431   | 12274.6 | 0.787 |       0.2 |
| businesses                   | NYC       | 11.2%        |         0.974 | 11.4%              |  406.7 |  2168.5 | 0.946 |       0.4 |
| businesses                   | Manhattan | 8.5%         |         0.968 | 5.3%               | 3909.7 |  6800.3 | 0.935 |       0.4 |
| common places                | NYC       | 12.3%        |         0.973 | 15.2%              |  446.8 |  2174.6 | 0.946 |       0.4 |
| common places                | Manhattan | 10.0%        |         0.959 | 15.6%              | 4582.9 |  7595.1 | 0.918 |       0.4 |
| POIs, equal weights          | NYC       | 10.7%        |         0.979 | 9.8%               |  391.6 |  1951.1 | 0.957 |       0.7 |
| POIs, equal weights          | Manhattan | 8.6%         |         0.968 | 9.4%               | 3974.1 |  6746.1 | 0.936 |       0.7 |
| POIs, CRIF weights (min-max) | NYC       | 9.9%         |         0.981 | 11.1%              |  361.1 |  1846.8 | 0.961 |       0.7 |
| POIs, CRIF weights (min-max) | Manhattan | 7.7%         |         0.972 | 4.6%               | 3558.2 |  6333.9 | 0.943 |       0.7 |
| historical (Jan 2013)        | NYC       | 2.1%         |         0.999 | 1.6%               |   75.4 |   529.2 | 0.997 |       9.6 |
| historical (Jan 2013)        | Manhattan | 1.9%         |         0.998 | 2.5%               |  870.2 |  1926.4 | 0.995 |       9.6 |
| blend, α = 0.5               | NYC       | 4.1%         |         0.997 | 3.2%               |  149.3 |   794.1 | 0.993 |      10   |
| blend, α = 0.5               | Manhattan | 3.5%         |         0.994 | 3.1%               | 1616.5 |  2892.7 | 0.988 |      10   |
| blend, α = 0.75              | NYC       | 2.9%         |         0.998 | 2.1%               |  105.4 |   603.4 | 0.996 |      11.1 |
| blend, α = 0.75              | Manhattan | 2.4%         |         0.997 | 2.7%               | 1126.5 |  2195.7 | 0.993 |      11.1 |
| blend, α = 0.9               | NYC       | 2.3%         |         0.999 | 1.7%               |   82.8 |   532.2 | 0.997 |      10.3 |
| blend, α = 0.9               | Manhattan | 2.0%         |         0.998 | 2.6%               |  897.7 |  1936.3 | 0.995 |      10.3 |
