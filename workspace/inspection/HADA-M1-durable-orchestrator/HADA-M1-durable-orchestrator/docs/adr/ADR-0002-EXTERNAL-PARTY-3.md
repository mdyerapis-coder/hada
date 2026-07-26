# ADR-0002: Party 3 remains outside HADA

**Status:** Accepted

Party 3 cannot run as another local agent controlled by HADA. HADA exports an evidence bundle and stops. An independent ChatGPT review is performed outside the appliance, then an approval or rejection artefact is imported and verified. This preserves reviewer independence and makes the stop condition technically enforceable.
