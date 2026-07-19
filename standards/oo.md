# Object-Oriented Discipline

This is the language-agnostic statement of the object-oriented stance shared
across Punt Labs. Three of our languages are object-oriented — Python, Swift,
and Pharo/Smalltalk — and this document describes the design discipline they
hold in common. The per-language standards realize this stance within their own
type systems and reference this document rather than restate it.

C and Go are outside this document. Each is idiomatic in its own paradigm, and
we write them that way; neither is trying to be object-oriented, so neither
answers to the discipline described here.

The point of writing the shared stance down once is that an agent moving between
repositories carries one idea of what a well-designed object is, and does not
relearn it in each language's dialect.

---

## The Reference Model: Pharo

When we want to see the stance in its clearest form, we look at
Pharo/Smalltalk. Pharo is purely object-oriented: everything is an object, and
every computation is a message sent to an object. There is no primitive that
sits outside the model, no operator that is secretly a function call on hidden
data. An integer is an object; `3 + 4` sends the message `+` to the object `3`
with the argument `4`, and the object decides what to do. Even a class is an
object, and even control flow is message sending — `ifTrue:ifFalse:` is a
message sent to a boolean.

Because Pharo has nothing but objects and messages, it shows the discipline with
no way to cheat. A behavior has to live on some object, because there is nowhere
else for it to live. A choice between cases has to be a message send, because
there is no free-floating switch statement to fall back on. Python and Swift do
not force this on you; they let you write a procedure that reaches into a record
and pulls its fields apart. Pharo does not offer that shortcut, which is exactly
why it is the reference. When you are unsure whether a Python or Swift design is
object-oriented, ask what its Pharo equivalent would be. If the answer is "a
message to the object that owns the state," the design is on the right track. If
the answer is "a function standing outside the object, reading its parts," it is
not.

---

## Behavior Lives With Its Data

An object owns its state and the operations on that state. This is the first
principle, and the others follow from it.

The failure it guards against is procedural code wearing an object's clothes. In
Python this shows up as a dataclass that holds fields and a pile of module-level
functions that read those fields, each one taking the dataclass as its first
argument. The class looks like an object, but it is only a record; the behavior
that belongs to it has been scattered into free functions. Lux carried this
pattern for a long time: each protocol element was a dataclass, and each kind
had a module-level `_kind_to_dict` and `_kind_from_dict` pair that reached into
its fields. That is a procedure operating on a structure, not an object doing its
own work. The correction is to move the behavior onto the class — `to_dict`
becomes an instance method, `from_dict` a class method — so the element serializes
itself instead of being serialized by an outside function.

In Pharo the question never arises, because there is nowhere to put the loose
function. An object that needs to print itself implements `printOn:`; the
knowledge of how the object appears lives with the object. When you find yourself
writing a function that takes an object, reads several of its fields, and returns
something derived from them, you have found a method that has escaped its class.
Put it back.

---

## Encapsulation: Tell, Don't Ask

An object exposes what it can do, not what it is made of. Callers ask the object
to perform work; they do not extract its data and perform the work themselves.
This is the difference between telling and asking. You tell an account to
`withdraw:` an amount and let it check its own balance; you do not ask it for its
balance, compare the numbers yourself, and then ask it to set a new one. The
second form has moved the account's logic into the caller, and now every caller
has to know the rule.

Encapsulation also means keeping your reach shallow. A method should talk to its
own object, the objects it was handed, and the objects it creates — not to the
objects that those objects happen to hold. When a chain of accessors walks from
one object into a second and then into a third, the caller has become entangled
with a structure two steps away, and a change to that distant structure will
break code that never should have known about it. This is the Law of Demeter,
and it is really a statement about who is allowed to know what. Ask the object in
front of you to do the work; let it ask its own collaborators in turn.

The reward is that an object's internals stay its own business. You can change
how an account stores its balance without touching a single caller, because no
caller ever looked.

---

## Polymorphism Over Conditionals

Dispatch on the object, not on a tag. When you find a `switch` or an
`if`-ladder that branches on a type field, an enum, or a string that names a
kind, you are doing by hand what the object system does for you. Each branch is a
method that belongs on the object being switched over, and the switch itself is a
method call waiting to be written.

Lux renders many kinds of element — text, button, checkbox, table, plot. The
procedural shape of that job is one large function that asks each element what
kind it is and branches accordingly. The object-oriented shape is that each
element kind renders itself, and the renderer simply sends the same message to
whatever element it holds. The migration Lux is undertaking moves the element
kinds onto exactly this footing: the conditional over kinds dissolves into a set
of classes, each answering the render message in its own way.

The test of the two designs is what happens when a new case arrives. With the
switch, you open every function that branches on the kind and add a case to each
one, and you hope you found them all. With polymorphism, you write one new class
that answers the messages, and the existing code dispatches to it without being
touched. New cases should arrive as new classes, not as new branches threaded
through old code. This is why Pharo can add a new kind of collection without
editing the collections that already exist — the new class simply implements the
collection protocol, and every client that spoke to that protocol now speaks to
the new class too.

---

## Composition Over Inheritance

Prefer assembling behavior from small collaborating objects to deriving it
through a deep class hierarchy. A hierarchy is rigid — a subclass is bound to its
superclass at every level, inherits everything the superclass has, and can be
understood only by reading the whole chain above it. A composition is loose — an
object holds another object and delegates to it, and either can be replaced
without disturbing the other.

Inheritance is not forbidden; it is reserved for its real purpose, which is
substitutability. A subclass should be usable everywhere its superclass is
expected, and should genuinely be a kind of what its parent is. When a subclass
overrides a method to mean something the parent never meant, or refuses part of
the interface it inherited, the "is a kind of" claim was false and the
inheritance was a mistake. The frequent temptation is to inherit purely to reuse
code — to make one class a subclass of another because the second happens to have
methods the first would like. That is composition misfiled as inheritance. Hold
the object you want to reuse and call it; do not become it.

The Strategy pattern is composition made deliberate: instead of subclassing to
vary one behavior, the object holds a separate strategy object and delegates the
varying decision to it. The Command pattern is the same move for actions — the
thing to be done becomes an object you can hold, pass, and store, rather than a
method fixed in a hierarchy. These patterns are popular precisely because they
trade a rigid inheritance relationship for a flexible compositional one.

---

## Families Share by Protocol, Not Base Class

A family of related types is defined by the messages its members answer, not by
a common ancestor they inherit from. What makes something a member of the family
is that it conforms to the interface — that it responds to the family's messages
— and conformance is enough. Pharo makes this vivid: any object that implements
`do:` can be iterated over, whether or not it descends from a shared collection
class. The protocol is the contract; the class tree is beside the point.

Python expresses this with a `runtime_checkable` `Protocol` — a structural type
that any class satisfies simply by having the right methods, with no base class
to inherit and no registration to perform. Lux's wire elements form a family this
way: each element class carries the type tag and the serialization methods the
family requires, and it belongs to the family by having them, not by descending
from a `BaseElement`. Swift expresses the same idea with its protocols, and its
value types conform to a protocol by implementing its requirements rather than by
subclassing.

The reason to prefer this over a shared base class is that a base class forces
its members into one implementation lineage and tempts you to push shared code
upward into the parent, where it hardens into a dependency every member carries
whether it needs it or not. A protocol asks only for behavior. It lets unrelated
implementations satisfy the same contract, and it lets a single type belong to
several families at once. Reserve the abstract base class for the rare case where
there is genuinely shared implementation that every member must have; let the
protocol define the family in every other case.

---

## Small, Focused Objects With One Responsibility

An object should have one responsibility and therefore one reason to change. This
is the principle that produces the many-small-classes design, and it is
consistently the harder discipline, because a large class that does several
things looks convenient right up until two of those things need to change in
different directions. The right number of classes for a working design is
usually more than you first think. When a class has grown to hold several
unrelated concerns, the move is to extract each concern into its own object and
let the original delegate to them — which is why refactoring is not a separate
activity from design but the loop through which good design is found.

The sharpest form of a focused object is one whose type makes its illegal states
unrepresentable. If a value cannot legitimately be absent, the type should not
admit absence; if two fields are valid only in certain combinations, the type
should encode the combinations rather than leave them to a comment and a runtime
check. A comment that lists the permitted values of a string is the type system
being asked to look the other way. Python replaces such a string with a
`Literal` of the exact allowed values, so the illegal ones cannot be written.
Swift's enumerations with associated values carry this further — a state that can
be one of several shapes, each with its own data, becomes a single type where no
invalid shape can be constructed. Lux applies the same reasoning when it splits a
response that carried an optional error field into a discriminated pair, one type
for success and one for failure, so that no value can claim to be both at once.
Every state you can make unrepresentable is a class of bug that can no longer be
written and a runtime check you no longer have to remember. Push the object's
constraints into its type, and let the compiler or the checker enforce what a
comment used to merely request.

---

## Realization and Enforcement

This document states the stance; it does not enforce it. Each language realizes
the discipline in its own idioms and holds the line with its own tooling. The
Python realization and its enforcement live in [python.md](python.md) and the
Python rules under `.claude/rules`, including the object-oriented ratchet that
measures every change. The Swift realization lives in swift.md and its
`.claude/rules`. The Pharo realization lives in pharo.md; its enforcement is
internal to the Pharo image, where the linting engine checks the code in place,
so there is no external rules file to point to. When a per-language rule and this
document appear to disagree, the language document governs the mechanics and this
one governs the intent — and they should be reconciled, not left in tension.
