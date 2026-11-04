// Where the drafting page sends AI requests (explain in plain English, rewrite to pass).
// The model's API key lives on the server function (supabase/functions/billcast in the
// Billcast repo) and never reaches the browser. The key below is Supabase's public
// browser key, which only lets the page call that function.
window.CO_AI = {
  endpoint: "https://taiehocnlzoscniyeyyk.supabase.co/functions/v1/billcast",
  anonKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRhaWVob2NubHpvc2NuaXlleXlrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI2ODc0NDMsImV4cCI6MjA5ODI2MzQ0M30.SSJz95hvHX_U2wG_h7nE2yG6iQhCpGOfurUb8_HkhQc",
};
