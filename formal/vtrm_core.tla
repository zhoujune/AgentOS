------------------------------ MODULE vtrm_core ------------------------------
EXTENDS TLC

\* A deliberately small abstract model of the VTRM decision core.
\*
\* Scope:
\* - a tiny request / state / decision transition system
\* - two core safety checks:
\*   1. denied requests do not mutate abstract state
\*   2. secret_high data is never allowed to an external_untrusted sink
\*
\* Non-goals:
\* - not a full model of AgentOS
\* - not a model of QEMU / Buildroot / WEJ / bridge / LLM behavior
\* - not a refinement proof of the Python implementation

CONSTANTS
    Paths,
    WorkspacePath,
    ProtectedPath,
    SecretPath

FileClasses == {"workspace_writable", "protected", "secret_source"}
Labels == {"public", "secret_high"}
SinkClasses == {"trusted_internal", "external_untrusted", "none"}
Tools == {"fs.read", "fs.write", "network.send"}
Decisions == {"Allow", "Deny"}

Requests ==
    { [tool      |-> t,
       path      |-> p,
       sinkClass |-> s,
       dataLabel |-> l] :
          t \in Tools,
          p \in Paths,
          s \in SinkClasses,
          l \in Labels }

VARIABLES
    fsClass,
    fsLabel,
    req,
    decision

vars == <<fsClass, fsLabel, req, decision>>

TypeInvariant ==
    /\ fsClass \in [Paths -> FileClasses]
    /\ fsLabel \in [Paths -> Labels]
    /\ req \in Requests
    /\ decision \in Decisions
    /\ WorkspacePath \in Paths
    /\ ProtectedPath \in Paths
    /\ SecretPath \in Paths

Init ==
    /\ fsClass =
        [p \in Paths |->
            IF p = WorkspacePath THEN "workspace_writable"
            ELSE IF p = ProtectedPath THEN "protected"
            ELSE "secret_source"]
    /\ fsLabel =
        [p \in Paths |->
            IF p = SecretPath THEN "secret_high" ELSE "public"]
    /\ req =
        [tool |-> "fs.read",
         path |-> WorkspacePath,
         sinkClass |-> "none",
         dataLabel |-> "public"]
    /\ decision = "Deny"

\* The abstract monitor decision function.
Evaluate(r, stateClass) ==
    IF r.tool = "network.send" THEN
        IF r.dataLabel = "secret_high" /\ r.sinkClass = "external_untrusted"
            THEN "Deny"
            ELSE "Allow"
    ELSE IF r.tool = "fs.write" THEN
        IF stateClass[r.path] = "workspace_writable"
            THEN "Allow"
            ELSE "Deny"
    ELSE IF r.tool = "fs.read" THEN
        IF stateClass[r.path] \in {"workspace_writable", "protected", "secret_source"}
            THEN "Allow"
            ELSE "Deny"
    ELSE "Deny"

\* Allowed workspace writes are the only abstract state mutation in this tiny model.
Next ==
    \E r \in Requests :
        LET d == Evaluate(r, fsClass) IN
        /\ req' = r
        /\ decision' = d
        /\ fsClass' = fsClass
        /\ fsLabel' =
            IF d = "Allow" /\ r.tool = "fs.write"
                THEN [fsLabel EXCEPT ![r.path] = r.dataLabel]
                ELSE fsLabel

Spec == Init /\ [][Next]_vars

\* ---------------------------------------------------------------------------
\* Safety checks
\* ---------------------------------------------------------------------------

\* State invariant: the current request / decision pair is never
\* "send secret_high to external_untrusted" together with Allow.
NoSecretToExternal ==
    ~(
        req.tool = "network.send"
        /\ req.dataLabel = "secret_high"
        /\ req.sinkClass = "external_untrusted"
        /\ decision = "Allow"
     )

\* Action property: if the next-state decision is Deny, abstract state does not change.
DenyHasNoEffect ==
    decision' = "Deny" => /\ fsClass' = fsClass
                          /\ fsLabel' = fsLabel

\* Simple sanity property: some requests are allowed in this model.
CanAllowSomething ==
    \E r \in Requests : Evaluate(r, fsClass) = "Allow"

\* Named temporal property for TLC configuration files.
DenyHasNoEffectAlways ==
    [][DenyHasNoEffect]_vars

=============================================================================
