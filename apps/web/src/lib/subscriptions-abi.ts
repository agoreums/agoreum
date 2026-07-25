/**
 * The subset of the AgoreumSubscriptions ABI the frontend calls directly.
 *
 * Only the two write functions a subscriber's wallet invokes are here; the full
 * ABI lives in packages/contracts and drives the backend indexer. Keeping this
 * minimal keeps the bundle small and the surface obvious.
 */
export const subscriptionsAbi = [
  {
    type: "function",
    name: "subscribe",
    stateMutability: "nonpayable",
    inputs: [
      { name: "planId", type: "uint256" },
      { name: "maxPrice", type: "uint256" },
    ],
    outputs: [],
  },
  {
    type: "function",
    name: "cancel",
    stateMutability: "nonpayable",
    inputs: [{ name: "planId", type: "uint256" }],
    outputs: [],
  },
] as const;

export default subscriptionsAbi;
