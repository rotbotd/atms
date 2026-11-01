{
  description = "atms: a small assumption-based truth maintenance system";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      src = pkgs.lib.fileset.toSource { root = ./.; fileset = pkgs.lib.fileset.unions [ ./atms.py ./test_atms.py ./demo.py ]; };
    in {
      checks.x86_64-linux.default = pkgs.runCommand "atms-tests" { nativeBuildInputs = [ pkgs.python3 ]; } ''
        cd ${src}
        PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_atms
        touch $out
      '';
      apps.x86_64-linux.demo = {
        type = "app";
        program = "${pkgs.writeShellScript "atms-demo" "cd ${src} && exec ${pkgs.python3}/bin/python3 demo.py"}";
      };
    };
}
