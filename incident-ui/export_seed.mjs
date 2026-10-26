import { INCIDENTS, DOCS } from "./src/mock.js";
console.log(JSON.stringify({ generated_at: new Date().toISOString(), incidents: INCIDENTS, documents: DOCS }, null, 2));
