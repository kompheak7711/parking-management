import { afterEach, describe, expect, it, vi } from "vitest";
import { sealedIntentStore, IntentStorageError } from "./sealedIntentStore";

afterEach(() => vi.unstubAllGlobals());
describe("actor and request identity before encryption or storage", () => {
  it.each(["\ud800", "\udfff", "actor-\ud800", "key-\udfff"])(
    "TEST-FE-285 rejects malformed Unicode identity before binding %s",
    async (invalid) => {
      const open = vi.fn(() => {
        throw new Error("No storage access expected");
      });
      const generateKey = vi.fn(() =>
        Promise.reject(new Error("No encryption expected")),
      );
      vi.stubGlobal("indexedDB", { open });
      vi.stubGlobal("crypto", { subtle: { generateKey } });
      await expect(
        sealedIntentStore.begin(invalid, {
          requestKey: "key",
          plaintext: "synthetic",
        }),
      ).rejects.toThrow(IntentStorageError);
      await expect(sealedIntentStore.read(invalid)).rejects.toThrow(
        IntentStorageError,
      );
      await expect(sealedIntentStore.clear(invalid, "key")).rejects.toThrow(
        IntentStorageError,
      );
      await expect(
        sealedIntentStore.begin("actor", {
          requestKey: invalid,
          plaintext: "synthetic",
        }),
      ).rejects.toThrow(IntentStorageError);
      await expect(sealedIntentStore.clear("actor", invalid)).rejects.toThrow(
        IntentStorageError,
      );
      expect(generateKey).not.toHaveBeenCalled();
      expect(open).not.toHaveBeenCalled();
    },
  );
  it.each(["", "x".repeat(1025)])(
    "TEST-FE-286 rejects empty or unbounded identities before storage",
    async (invalid) => {
      const open = vi.fn(() => {
        throw new Error("No storage expected");
      });
      vi.stubGlobal("indexedDB", { open });
      await expect(sealedIntentStore.read(invalid)).rejects.toThrow(
        IntentStorageError,
      );
      await expect(sealedIntentStore.clear("actor", invalid)).rejects.toThrow(
        IntentStorageError,
      );
      expect(open).not.toHaveBeenCalled();
    },
  );
});
