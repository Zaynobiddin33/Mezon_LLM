import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services, stats
from .ai import get_analyzer
from .models import Analysis, Document, Region, RegulationRequest


def _table():
    # annotate() drops Meta.ordering (GROUP BY), so order explicitly
    return (RegulationRequest.objects.select_related("region")
            .annotate(doc_count=Count("documents")).order_by("-submitted_at"))


def dashboard(request):
    hour = timezone.localtime().hour
    return render(request, "regulations/dashboard.html", {
        **stats.dashboard(),
        "greeting": "Xayrli tong" if 5 <= hour < 12 else "Xayrli kun" if hour < 18 else "Xayrli kech",
        "recent": _table()[:8],
        "next_open": RegulationRequest.objects.filter(status__in=RegulationRequest.OPEN_STATUSES).order_by("submitted_at").first(),
        "nav": "dashboard",
    })


def request_list(request):
    qs = _table()
    status = request.GET.get("holat", "")
    region = request.GET.get("hudud", "")
    q = request.GET.get("q", "").strip()
    if status == "jarayonda":
        qs = qs.filter(status__in=RegulationRequest.OPEN_STATUSES)
    elif status in ("accepted", "rejected"):
        qs = qs.filter(status=status)
    if region:
        qs = qs.filter(region__code=region)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q) | Q(issuer_name__icontains=q) | Q(district__icontains=q))
    tabs = [("", "Barchasi"), ("jarayonda", "Jarayonda"), ("accepted", "Qabul qilingan"), ("rejected", "Rad etilgan")]
    return render(request, "regulations/request_list.html", {
        "page": Paginator(qs, 20).get_page(request.GET.get("page")),
        "tabs": tabs, "status": status, "region": region, "q": q,
        "regions": Region.objects.all(), "nav": "requests",
    })


def review(request, pk):
    req = get_object_or_404(RegulationRequest.objects.select_related("region"), pk=pk)
    services.mark_opened(req, request.user)
    analysis = req.analyses.filter(state=Analysis.State.DONE).prefetch_related("findings").first()
    last = req.analyses.first()
    failed = last if last and last.state == Analysis.State.FAILED and (
        not analysis or last.started_at > analysis.started_at) else None
    return render(request, "regulations/review.html", {
        "req": req,
        "documents": req.documents.all(),
        "analysis": analysis,
        "failed": failed,
        "autostart": analysis is None and failed is None and req.is_open,
        "chat": req.messages.all(),
        "decision": req.decision,
        "analyzer": get_analyzer(),
        "auto_prompt": services.AUTO_PROMPT,
        "nav": "requests",
    })


def _stream(events):
    def body():
        yield ": mezon\n\n"  # opens the stream right away
        for event in events:
            yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"
    resp = StreamingHttpResponse(body(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_POST
def analyze(request, pk):
    req = get_object_or_404(RegulationRequest, pk=pk)
    return _stream(services.run_analysis(req, request.user))


@require_POST
def chat(request, pk):
    req = get_object_or_404(RegulationRequest, pk=pk)
    message = (request.POST.get("message") or "").strip()[:4000]
    if not message:
        return HttpResponse(status=400)
    return _stream(services.run_chat(req, request.user, message))


@require_POST
def decide(request, pk):
    req = get_object_or_404(RegulationRequest, pk=pk)
    outcome, comment = request.POST.get("outcome", ""), request.POST.get("comment", "")
    if outcome == "reject" and not comment.strip():
        messages.error(request, "Rad etish sababini yozing.")
    else:
        try:
            decision = services.decide(req, request.user, outcome, comment)
            messages.success(request, f"{req.number} · {decision.get_outcome_display()}")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("review", pk=pk)


def document_download(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if doc.file:
        return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.file.name.rsplit("/", 1)[-1])
    if not doc.text:
        raise Http404
    resp = HttpResponse(doc.text, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{doc.request.number}-{doc.pk}.txt"'
    return resp
