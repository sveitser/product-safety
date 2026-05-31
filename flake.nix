{
  description = "Product Safety DB — EU Safety Gate alerts with better UX";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pre-commit-hooks.url = "github:cachix/pre-commit-hooks.nix";
  };

  outputs = { self, nixpkgs, flake-utils, pre-commit-hooks }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
        pythonEnv = python.withPackages (ps: with ps; [
          fastapi
          uvicorn
          jinja2
          python-multipart
          aiosqlite
          httpx
          pydantic
          pydantic-settings
          rich
          typer
          # test / dev
          pytest
          pytest-cov
          pytest-asyncio
          starlette
        ]);

        checks = {
          pre-commit-check = pre-commit-hooks.lib.${system}.run {
            src = ./.;
            hooks = {
              ruff = {
                enable = true;
                args = [ "check" "--fix" ];
              };
              ruff-format = {
                enable = true;
              };
              ty = {
                enable = true;
                name = "ty";
                entry = "${pkgs.ty}/bin/ty check";
                language = "system";
                pass_filenames = false;
                types = [ "python" ];
              };
              pytest = {
                enable = true;
                name = "pytest";
                entry = "${pythonEnv}/bin/python -m pytest --tb=short -q --cov=backend --cov=scraper --cov-fail-under=98";
                language = "system";
                pass_filenames = false;
                types = [ "python" ];
              };
            };
          };
        };
      in
      {
        inherit checks;

        devShells.default = pkgs.mkShell {
          inherit (checks.pre-commit-check) shellHook;
          packages = [
            pythonEnv
            pkgs.ty
            pkgs.sqlite
            pkgs.litecli
            pkgs.jq
            pkgs.curl
          ];

          shellHook = ''
            ${checks.pre-commit-check.shellHook}
            export PROJECT_ROOT="$(pwd)"
            export DATA_DIR="$PROJECT_ROOT/data"
            export DB_PATH="$DATA_DIR/safety.db"
            export IMAGES_DIR="$DATA_DIR/images"
            echo "Product Safety DB dev shell"
            echo "  Scrape:       python scraper/ingest.py"
            echo "  Serve:        uvicorn backend.app.main:app --reload"
            echo "  Test:         pytest"
            echo "  Coverage:     pytest --cov=backend --cov=scraper --cov-report=term-missing"
            echo "  Uncovered:    pytest --cov=backend --cov=scraper --cov-report=term-missing 2>&1 | grep -v '100%'"
          '';
        };
      });
}
