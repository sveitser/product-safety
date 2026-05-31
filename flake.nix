{
  description = "Product Safety DB — EU Safety Gate alerts with better UX";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
        pythonEnv = python.withPackages (ps: with ps; [
          # web framework
          fastapi
          uvicorn
          jinja2
          python-multipart
          # database
          aiosqlite
          # scraper
          httpx
          # utilities
          pydantic
          pydantic-settings
          rich
          typer
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            pythonEnv
            pkgs.sqlite
            pkgs.litecli
            pkgs.jq
            pkgs.curl
          ];

          shellHook = ''
            export PROJECT_ROOT="$(pwd)"
            export DATA_DIR="$PROJECT_ROOT/data"
            export DB_PATH="$DATA_DIR/safety.db"
            export IMAGES_DIR="$DATA_DIR/images"
            echo "Product Safety DB dev shell"
            echo "  Run scraper:  python scraper/ingest.py"
            echo "  Run backend:  uvicorn backend.app.main:app --reload"
          '';
        };

        packages.default = pkgs.writeShellApplication {
          name = "product-safety-scraper";
          runtimeInputs = [ pythonEnv ];
          text = ''
            cd "$PROJECT_ROOT"
            python scraper/ingest.py "$@"
          '';
        };
      });
}
