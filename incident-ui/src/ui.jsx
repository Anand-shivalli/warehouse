export const Btn = ({ children, kind = "primary", ...p }) => (
  <button {...p} className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:cursor-not-allowed disabled:opacity-40 ${
    { primary: "bg-blue-600 text-white hover:bg-blue-500", ghost: "bg-[#262626] text-neutral-200 hover:bg-[#303030]", danger: "bg-red-900/60 text-red-200 hover:bg-red-900" }[kind]}`}>{children}</button>
);
export const inp = "w-full rounded-lg border border-white/10 bg-[#111] px-3 py-2 text-sm text-neutral-100 placeholder-neutral-600 focus:border-blue-500 focus:outline-none";