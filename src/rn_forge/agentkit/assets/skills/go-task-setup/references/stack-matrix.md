# Stack matrix

Per-stack command mappings for filling `tasks/quality.yml` and the namespace files (SKILL.md §2).

**Read these out of the repo's own config — this table is a starting point, not an authority.** A
repo with a `[tool.ruff]` section and no ruff in its dev-dependencies is telling you something. When
the repo's real command differs from the row below, the repo wins.

## Backends

| | Python (uv) | Python (Poetry) | Java (Gradle) | Java (Maven) | Go | Rust |
|---|---|---|---|---|---|---|
| **detect** | `uv.lock` | `poetry.lock` | `settings.gradle{,.kts}` | `pom.xml` | `go.mod` | `Cargo.toml` |
| **install** | `uv sync --all-packages` | `poetry install` | — (resolves on demand) | `mvn -q dependency:go-offline` | `go mod download` | `cargo fetch` |
| **lint** | `uv run ruff check .` | `poetry run ruff check .` | `./gradlew spotlessCheck checkstyleMain` | `mvn -q checkstyle:check` | `golangci-lint run` | `cargo clippy -- -D warnings` |
| **format** | `uv run ruff format .` | `poetry run ruff format .` | `./gradlew spotlessApply` | `mvn -q spotless:apply` | `go fmt ./...` | `cargo fmt` |
| **typecheck** | `uv run mypy .` | `poetry run mypy .` | *(none — see below)* | *(none — see below)* | *(none — `go build` covers it)* | `cargo check` |
| **test** | `uv run pytest` | `poetry run pytest` | `./gradlew test` | `mvn -q test` | `go test ./...` | `cargo test` |
| **build** | — | — | `./gradlew build -x test` | `mvn -q package -DskipTests` | `go build ./...` | `cargo build --release` |
| **dev** | `uv run uvicorn ...` | `poetry run uvicorn ...` | `./gradlew bootRun` | `mvn spring-boot:run` | `go run ./cmd/...` | `cargo run` |

**Plain pip/venv:** install is `pip install -e '.[dev]'` and there is no run-prefix — commands are bare
(`ruff check .`), which assumes the venv is active. Say so in the design doc; it is the one stack where
`task` cannot fully insulate the developer from the toolchain.

## Frontends

| | pnpm | npm | yarn | bun |
|---|---|---|---|---|
| **detect** | `pnpm-lock.yaml` | `package-lock.json` | `yarn.lock` | `bun.lockb` |
| **install** | `pnpm install` | `npm ci` | `yarn install --immutable` | `bun install` |
| **run a binary** | `pnpm exec <bin>` | `npx <bin>` | `yarn <bin>` | `bunx <bin>` |
| **scope to one app** | `pnpm --filter <app> exec` | `npm -w <app> exec` | `yarn workspace <app>` | `bun --filter <app>` |

Tools are then the usual ones — `eslint .`, `prettier --write .`, `tsc --noEmit -p tsconfig.json`,
`vitest run --coverage` / `jest --coverage`, `playwright test`. Read `package.json` devDependencies
rather than assuming which of Vitest/Jest is present.

**Nx or Turborepo already present?** Don't duplicate their graph. Inner tasks delegate — `pnpm exec nx
run-many -t test` or `pnpm exec turbo run test` — and go-task stays the polyglot layer above them.

## Verb-set adaptations

The eight top-level verbs are not universal. Decide deliberately and record the decision in the design
doc; an aggregate wrapper dispatching to nothing is worse than an absent verb.

- **Java has no `typecheck`.** Compilation *is* typechecking. Either drop the verb and let `build`
  carry it, or keep `typecheck` as frontend-only (`tsc --noEmit`) and say so in its `desc:`. Don't
  invent a `typecheck:backend` that runs `./gradlew compileJava` twice over what `test` already did.
- **Go has no `install`.** `go mod download` is a warm-cache step, not a prerequisite. Keep it in
  `setup` if CI benefits; don't create a `go:install` namespace task nothing depends on.
- **Gradle and Maven are already task runners.** Expect the "why wrap a wrapper" objection in review.
  The answer is that the wrapper unifies *across* Gradle and pnpm — a single `task test` that means
  both — which no per-language runner can do. Put that answer in the design doc, not just in a PR
  reply, or the setup gets removed by the next person who doesn't see the point.
- **Rust's `cargo check` maps cleanly to `typecheck`**, and `cargo clippy` to `lint`. This is the one
  backend where all eight verbs land naturally.

## Forbidden-tool lists for `check_ci_entrypoint`

The list is every binary the vocabulary wraps, so CI can't route around it:

- **Python + pnpm:** `uv`, `pnpm`, `npx`, `pytest`, `ruff`, `mypy`
- **Java (Gradle) + React/npm:** `mvn`, `gradle`, `gradlew`, `npm`, `npx`, `jest`
- **Go + pnpm:** `go`, `golangci-lint`, `pnpm`, `npx`
- **Rust + pnpm:** `cargo`, `pnpm`, `npx`

Include the wrapper script name (`gradlew`) as well as the binary (`gradle`) — `./gradlew test` in a CI
step is the exact thing this check exists to catch.
