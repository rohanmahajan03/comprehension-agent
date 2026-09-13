# Sample chapter — single-variable calculus

Paste-ready chapter text for exercising the app against the real LLM services. Written for
graph review mode in particular (`docs/specs/2026-09-12-human-in-the-loop`), where the point
is to look at an extracted graph and judge it — which needs a chapter whose prerequisite
structure you already know.

**To run it through review mode:** set `LLM_API_KEY` in `.env`, `docker compose up`, paste
the block below into "Upload a chapter", and tick **"Review the concept graph first"**
before submitting. You'll land on the review screen rather than the graph. Extraction is one
real (cheap) call; approving spends one more per concept, so expect roughly six calls for a
full run. Leave the box unticked and the chapter goes straight through to questions, which
is also a fine way to test the ordinary path.

**What a good extraction looks like here.** Around five concepts — limits, continuity, the
derivative, the chain rule, implicit differentiation — chained:

```
limits → continuity → derivative → chain rule → implicit differentiation
```

(the derivative depends on both limits and continuity). Every one of those dependencies is
stated outright in a sentence the extractor can quote as edge evidence, which is what makes
this text a useful test rather than just a sample: when an edge comes back missing, you can
point at the sentence it should have come from. `tests/graph_geval` has repeatedly shown
under-connection to be the extractor's weakest area, so a missing backbone edge here is the
expected failure, not a surprise — and repairing it by hand is exactly what review mode is
for.

---

```text
Limits

The limit is the idea the rest of calculus is built on. Writing lim(x→a) f(x) = L means
that we can make the value of f(x) as close to L as we like by taking x close enough to a
— while never letting x equal a. That last restriction is not a technicality; it is the
entire source of the limit's usefulness. Because the value at a is excluded, a function can
have a perfectly well-behaved limit at a point where it is not even defined.

The standard illustration is f(x) = (x² − 1)/(x − 1). At x = 1 this expression is 0/0, which
is meaningless, so f(1) does not exist. But for every other x the numerator factors and the
fraction simplifies to x + 1. As x is taken closer and closer to 1 from either side, f(x) is
taken closer and closer to 2, and so lim(x→1) f(x) = 2. The limit describes where the
function is headed, not where it arrives, and those two questions can have different answers
— or only one answer, when the other is undefined.

A limit need not exist. If a function approaches one value from the left and a different
value from the right, no single number satisfies the definition, and we say the limit fails
to exist at that point. Checking a two-sided limit therefore means checking two one-sided
limits and asking whether they agree.

Continuity

Continuity is defined in terms of limits. A function f is continuous at a point a when
lim(x→a) f(x) = f(a). Because continuity is stated as an equation about a limit, there is no
way to decide whether a function is continuous without first being able to evaluate its
limits.

That single equation quietly demands three separate things. The function must actually be
defined at a, so that f(a) names a number. The limit must exist, so that the left-hand side
names a number. And the two numbers must be equal. A function can fail to be continuous by
failing any one of these, which is why the classification of discontinuities has more than
one case: a removable discontinuity, where the limit exists but disagrees with the value, is
a different failure from a jump, where the one-sided limits disagree with each other.

Informally, continuity is what licenses the picture of a curve drawn without lifting the
pen. The formal definition is what makes that picture usable, because it is stated about a
single point and can therefore be checked point by point.

The derivative

The derivative of f at a is defined as a limit of difference quotients:

    f'(a) = lim(h→0) [ f(a + h) − f(a) ] / h

Each quotient in this expression is the slope of the secant line through two points on the
graph, one at a and one h units away. As h shrinks, those secant lines pivot toward a single
limiting position, and the derivative is the slope of that limiting line — the tangent.
Since the derivative is itself a limit, every property of derivatives inherits from the
theory of limits, and a derivative fails to exist precisely when the defining limit fails to
exist.

Differentiability is a stronger condition than continuity. If f is differentiable at a, then
f is continuous at a: a function cannot have a tangent line at a point where it jumps. The
converse does not hold. The absolute value function is continuous everywhere, but at x = 0
its difference quotients approach −1 from the left and +1 from the right, so the defining
limit does not exist and the function is not differentiable there. Continuity is therefore
necessary for differentiability but not sufficient for it, and a corner is the standard
example separating the two.

The chain rule

Most functions worth differentiating are built out of simpler ones, and composition is the
most common way of building them. The chain rule states that if y = f(g(x)), then

    (f ∘ g)'(x) = f'(g(x)) · g'(x)

The derivative of the composition is the derivative of the outer function, evaluated at the
inner function, times the derivative of the inner function. Because the chain rule is a
statement about the derivatives of the functions being composed, it cannot be applied until
each of those functions can be differentiated on its own; it combines derivatives rather
than producing them from nothing.

Reading the rule as a statement about rates makes it easier to remember. If y changes three
times as fast as u, and u changes five times as fast as x, then y changes fifteen times as
fast as x. The factors multiply because the intermediate quantity is shared: the inner
function's rate is the scale on which the outer function's rate is measured.

Implicit differentiation

Not every relationship between two variables can be solved for one of them. The circle
x² + y² = 25 defines y as a function of x only locally, and solving gives two separate
branches rather than one formula. Implicit differentiation is a technique for finding dy/dx
directly from such an equation, without solving for y first.

The method is to differentiate both sides of the equation with respect to x, treating y
throughout as an unspecified function of x. Every term containing y is therefore a
composition, and differentiating it requires the chain rule: the derivative of y² with
respect to x is 2y · (dy/dx), not 2y. This is why implicit differentiation cannot be
performed without the chain rule — the chain rule is what produces the dy/dx factors that
the method then solves for.

Applied to the circle, differentiating both sides gives 2x + 2y·(dy/dx) = 0, and solving
yields dy/dx = −x/y. The result is expressed in terms of both variables, which is
characteristic of the method: an implicit equation describes a curve, and the slope at a
point on that curve generally depends on which point you are standing at.
```
