import { createHash, randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";

import { duration, pct, short } from "./format";
import { en, ur } from "./messages";
import { sha256Bytes, sha256File } from "./sha256";

const utf8 = (s: string) => new TextEncoder().encode(s);
const nodeSha = (b: Uint8Array) => createHash("sha256").update(b).digest("hex");

describe("sha256 fallback (verify portal on a plain-HTTP LAN)", () => {
  it("matches the FIPS 180-2 test vectors", () => {
    expect(sha256Bytes(utf8(""))).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Bytes(utf8("abc"))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Bytes(utf8("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"))).toBe("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  });

  it("agrees with node:crypto on every padding boundary and on large input", () => {
    for (const n of [1, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000, 70_000]) {
      const data = new Uint8Array(randomBytes(n));
      expect(sha256Bytes(data), `length ${n}`).toBe(nodeSha(data));
    }
  });

  it("hashes a file outside a secure context with the fallback", async () => {
    const data = new Uint8Array(randomBytes(5000));
    expect(await sha256File(new Blob([data]))).toBe(nodeSha(data));
  });
});

function keys(o: unknown, prefix = ""): string[] {
  if (typeof o !== "object" || o === null) return [prefix];
  return Object.entries(o).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("messages", () => {
  it("Urdu and English have exactly the same keys", () => {
    expect(keys(en).sort()).toEqual(keys(ur).sort());
  });

  it("no string is empty", () => {
    const empty = (m: unknown) => keys(m).filter((k) => k.split(".").reduce<unknown>((o, p) => (o as Record<string, unknown>)[p], m) === "");
    expect(empty(ur)).toEqual([]);
    expect(empty(en)).toEqual([]);
  });
});

describe("format", () => {
  it("duration, pct, short", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(125)).toBe("2m 05s");
    expect(duration(null)).toBe("—");
    expect(pct(0.1234)).toBe("12.3%");
    expect(short("a".repeat(64))).toBe(`${"a".repeat(10)}…${"a".repeat(6)}`);
    expect(short("abc")).toBe("abc");
  });
});
