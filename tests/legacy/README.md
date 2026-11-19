# Legacy code for comparison tests

Copies of the code urbanweave replaces, run beside it in the tests so that every difference in
output has a named cause. They are test fixtures only: urbanweave does not import them, and they are
not part of the installed package. Each folder's `REVISION` records the source repository and commit.

- `urbantrace/`: integration operators and the H3 grid of
  [VIDA-NYU/urbanTrace](https://github.com/VIDA-NYU/urbanTrace).
- `curio/`: the UHVI and Weather zonal means of
  [urban-toolkit/curio](https://github.com/urban-toolkit/curio), under Curio's MIT license (`curio/LICENSE`).
