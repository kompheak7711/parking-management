/** Exact JSON for financial wire values; decimals never pass through Number. */
export const FINANCIAL_BODY_BYTES = 262_144;
const numericLiteral = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

export class FinancialJsonError extends Error {
  constructor() {
    super("Invalid or oversized financial JSON.");
    this.name = "FinancialJsonError";
  }
}

export class ExactJsonNumber {
  readonly literal: string;
  constructor(literal: string) {
    if (typeof literal !== "string" || !numericLiteral.test(literal))
      throw new FinancialJsonError();
    this.literal = literal;
    Object.freeze(this);
  }
  toString(): string {
    return this.literal;
  }
  toJSON(): never {
    // Accidental native serialization must not silently change a numeric value.
    throw new FinancialJsonError();
  }
}

export type FinancialJson =
  | null
  | boolean
  | string
  | number
  | bigint
  | ExactJsonNumber
  | FinancialJson[]
  | { [key: string]: FinancialJson };

function validLimit(limit: number): void {
  if (!Number.isSafeInteger(limit) || limit < 1) throw new FinancialJsonError();
}
function validUnicode(text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(++index);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new FinancialJsonError();
    } else if (code >= 0xdc00 && code <= 0xdfff) throw new FinancialJsonError();
  }
}
function bytes(text: string, limit: number): number {
  if (text.length > limit) throw new FinancialJsonError();
  validUnicode(text);
  const length = new TextEncoder().encode(text).byteLength;
  if (length > limit) throw new FinancialJsonError();
  return length;
}

interface ArrayFrame {
  kind: "array";
  result: FinancialJson[];
  state: "first" | "value" | "comma";
}
interface ObjectFrame {
  kind: "object";
  result: Record<string, FinancialJson>;
  keys: Set<string>;
  key: string;
  state: "first" | "key" | "colon" | "value" | "comma";
}

/** Byte-bounded, iterative parsing also rejects duplicate decoded object keys. */
export function parseFinancialJson(
  raw: string,
  maxBytes = FINANCIAL_BODY_BYTES,
): FinancialJson {
  validLimit(maxBytes);
  if (typeof raw !== "string") throw new FinancialJsonError();
  bytes(raw, maxBytes);
  let position = 0;
  const frames: (ArrayFrame | ObjectFrame)[] = [];
  function whitespace(): void {
    while (/[\x20\t\r\n]/.test(raw[position] ?? "!")) position += 1;
  }
  function string(): string {
    const start = position;
    if (raw[position++] !== '"') throw new FinancialJsonError();
    while (position < raw.length) {
      const character = raw[position++];
      if (character === "\\") position += 1;
      else if (character === '"') {
        try {
          const parsed: unknown = JSON.parse(raw.slice(start, position));
          if (typeof parsed !== "string") throw new FinancialJsonError();
          validUnicode(parsed);
          return parsed;
        } catch {
          throw new FinancialJsonError();
        }
      }
    }
    throw new FinancialJsonError();
  }
  function value(): FinancialJson {
    whitespace();
    const character = raw[position];
    if (character === '"') return string();
    if (character === "[") {
      position += 1;
      const result: FinancialJson[] = [];
      frames.push({ kind: "array", result, state: "first" });
      return result;
    }
    if (character === "{") {
      position += 1;
      const result: Record<string, FinancialJson> = {};
      frames.push({
        kind: "object",
        result,
        keys: new Set(),
        key: "",
        state: "first",
      });
      return result;
    }
    for (const [token, result] of [
      ["true", true],
      ["false", false],
      ["null", null],
    ] as const) {
      if (raw.startsWith(token, position)) {
        position += token.length;
        return result;
      }
    }
    const literal =
      /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(
        raw.slice(position),
      )?.[0];
    if (!literal) throw new FinancialJsonError();
    position += literal.length;
    if (literal === "-0" || /[.eE]/.test(literal))
      return new ExactJsonNumber(literal);
    const integer = BigInt(literal);
    return integer >= BigInt(Number.MIN_SAFE_INTEGER) &&
      integer <= BigInt(Number.MAX_SAFE_INTEGER)
      ? Number(integer)
      : integer;
  }
  const result = value();
  while (frames.length) {
    const frame = frames[frames.length - 1];
    if (!frame) throw new FinancialJsonError();
    whitespace();
    if (frame.state === "comma") {
      if (raw[position] === ",") {
        position += 1;
        frame.state = frame.kind === "array" ? "value" : "key";
      } else if (raw[position] === (frame.kind === "array" ? "]" : "}")) {
        position += 1;
        frames.pop();
      } else throw new FinancialJsonError();
    } else if (frame.kind === "array") {
      if (frame.state === "first" && raw[position] === "]") {
        position += 1;
        frames.pop();
      } else {
        frame.state = "comma";
        frame.result.push(value());
      }
    } else if (frame.state === "first" || frame.state === "key") {
      if (frame.state === "first" && raw[position] === "}") {
        position += 1;
        frames.pop();
      } else {
        frame.key = string();
        if (frame.keys.has(frame.key)) throw new FinancialJsonError();
        frame.keys.add(frame.key);
        frame.state = "colon";
      }
    } else if (frame.state === "colon") {
      if (raw[position++] !== ":") throw new FinancialJsonError();
      frame.state = "value";
    } else {
      frame.state = "comma";
      Object.defineProperty(frame.result, frame.key, {
        value: value(),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
  }
  whitespace();
  if (position !== raw.length) throw new FinancialJsonError();
  return result;
}

type WriteStep =
  | { kind: "value"; value: unknown }
  | { kind: "text"; text: string }
  | { kind: "leave"; value: object };

/** Serializes exact integer/decimal tokens without invoking getters or toJSON. */
export function stringifyFinancialJson(
  value: unknown,
  maxBytes = FINANCIAL_BODY_BYTES,
): string {
  validLimit(maxBytes);
  const active = new WeakSet();
  const stack: WriteStep[] = [{ kind: "value", value }];
  const output: string[] = [];
  let size = 0;
  function emit(text: string): void {
    size += bytes(text, maxBytes);
    if (size > maxBytes) throw new FinancialJsonError();
    output.push(text);
  }
  while (stack.length) {
    const step = stack.pop();
    if (!step) throw new FinancialJsonError();
    if (step.kind === "text") {
      emit(step.text);
      continue;
    }
    if (step.kind === "leave") {
      active.delete(step.value);
      continue;
    }
    const current = step.value;
    if (current === null) emit("null");
    else if (typeof current === "string") {
      validUnicode(current);
      emit(JSON.stringify(current));
    } else if (typeof current === "boolean") emit(String(current));
    else if (typeof current === "bigint") emit(current.toString());
    else if (typeof current === "number") {
      if (!Number.isSafeInteger(current)) throw new FinancialJsonError();
      emit(Object.is(current, -0) ? "-0" : String(current));
    } else if (current instanceof ExactJsonNumber) {
      if (
        typeof current.literal !== "string" ||
        !numericLiteral.test(current.literal)
      )
        throw new FinancialJsonError();
      emit(current.literal);
    } else if (typeof current === "object") {
      if (active.has(current)) throw new FinancialJsonError();
      const array = Array.isArray(current);
      if (
        Object.getPrototypeOf(current) !==
          (array ? Array.prototype : Object.prototype) &&
        Object.getPrototypeOf(current) !== null
      )
        throw new FinancialJsonError();
      const keys = Object.keys(current);
      if (
        keys.length > maxBytes ||
        Object.getOwnPropertySymbols(current).length ||
        (array && keys.length !== current.length)
      )
        throw new FinancialJsonError();
      const descriptors = Object.getOwnPropertyDescriptors(current);
      active.add(current);
      stack.push({ kind: "leave", value: current });
      stack.push({ kind: "text", text: array ? "]" : "}" });
      for (let index = keys.length - 1; index >= 0; index -= 1) {
        const key = array ? String(index) : keys[index];
        if (key === undefined) throw new FinancialJsonError();
        const descriptor = descriptors[key];
        if (!descriptor || !("value" in descriptor))
          throw new FinancialJsonError();
        stack.push({ kind: "value", value: descriptor.value as unknown });
        if (!array) {
          validUnicode(key);
          stack.push({ kind: "text", text: JSON.stringify(key) + ":" });
        }
        if (index > 0) stack.push({ kind: "text", text: "," });
      }
      emit(array ? "[" : "{");
    } else throw new FinancialJsonError();
  }
  return output.join("");
}
