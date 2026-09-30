const fs = require("fs");
const v = require("../../frontend/assets/verify.js");
const variants = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = variants.map((x) => {
  const rep = v.verify(x.cert, x.bundle, x.onchain);
  return rep.rows.map((r) => [r.name, r.status]);
});
process.stdout.write(JSON.stringify(out));
