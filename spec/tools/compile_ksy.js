// Compile a .ksy file to a Python parser using the kaitai-struct-compiler JS build.
// Usage: node compile_ksy.js <input.ksy> <out_dir>
// The kaitai-struct-compiler and js-yaml modules are expected on NODE_PATH
// (the PoC installs them in the session scratchpad; see spec/README.md).
const fs = require("fs");
const path = require("path");
const compiler = require("kaitai-struct-compiler");
const yaml = require("js-yaml");

const [, , ksyPath, outDir] = process.argv;
if (!ksyPath || !outDir) {
  console.error("usage: node compile_ksy.js <input.ksy> <out_dir>");
  process.exit(2);
}
const ksy = yaml.load(fs.readFileSync(ksyPath, "utf8"));
const ksyDir = path.dirname(ksyPath);
const yamlImporter = {
  importYaml: function(name, mode) {
    const file = name.endsWith(".ksy") ? name : `${name}.ksy`;
    const importPath = path.isAbsolute(file) ? file : path.join(ksyDir, file);
    const importKsy = yaml.load(fs.readFileSync(importPath, "utf8"));
    return Promise.resolve(importKsy);
  },
};
compiler
  .compile("python", ksy, yamlImporter, false)
  .then((files) => {
    fs.mkdirSync(outDir, { recursive: true });
    for (const name of Object.keys(files)) {
      fs.writeFileSync(path.join(outDir, name), files[name].replace(/[ \t]+$/gm, ""));
      console.log("wrote", name);
    }
  })
  .catch((err) => {
    console.error("compile failed:", err);
    process.exit(1);
  });
