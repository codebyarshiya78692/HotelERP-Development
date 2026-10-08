from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render

from orders.models import DiningSession

from .models import Feedback


def create_feedback(request, session_id):
    """
    Allow a customer to submit feedback for a completed
    dining session.

    Login is not required.
    """

    session = get_object_or_404(
        DiningSession.objects.select_related("table"),
        id=session_id,
    )

    if request.user.is_authenticated and request.user.is_staff:
        messages.warning(
            request,
            "Staff members cannot submit customer feedback.",
        )
        return redirect("admin:index")

    if session.status != "completed":
        messages.warning(
            request,
            "Feedback can only be submitted after your dining "
            "session has been completed.",
        )

        if request.user.is_authenticated:
            return redirect("accounts:my_orders")

        return redirect("/")

    if Feedback.objects.filter(
        session=session,
    ).exists():
        messages.info(
            request,
            "Feedback has already been submitted for this session.",
        )

        if request.user.is_authenticated:
            return redirect("accounts:my_orders")

        return redirect("/")

    if request.method == "POST":
        rating = request.POST.get("rating")
        comment = request.POST.get("comment", "").strip()
        would_recommend = request.POST.get("would_recommend")

        try:
            rating_value = int(rating)
        except (TypeError, ValueError):
            rating_value = None

        if rating_value not in range(1, 6):
            messages.error(
                request,
                "Please select a rating between 1 and 5.",
            )

            return render(
                request,
                "feedback/form.html",
                {
                    "session": session,
                    "rating": rating,
                    "comment": comment,
                    "would_recommend": would_recommend,
                },
            )

        if would_recommend not in {"yes", "no"}:
            messages.error(
                request,
                "Please tell us whether you would recommend us.",
            )

            return render(
                request,
                "feedback/form.html",
                {
                    "session": session,
                    "rating": rating,
                    "comment": comment,
                    "would_recommend": would_recommend,
                },
            )

        Feedback.objects.create(
            session=session,
            rating=rating_value,
            comment=comment,
            would_recommend=would_recommend == "yes",
        )

        messages.success(
            request,
            "Thank you! Your feedback has been submitted.",
        )

        if request.user.is_authenticated:
            return redirect("accounts:my_orders")

        return redirect("/")

    return render(
        request,
        "feedback/form.html",
        {
            "session": session,
        },
    )


@login_required
def dashboard(request):
    """
    Staff feedback dashboard.
    """

    if not request.user.is_staff:
        return render(
            request,
            "feedback/access_denied.html",
            status=403,
        )

    feedback_queryset = Feedback.objects.select_related(
        "session",
        "session__table",
    )

    total_feedback = feedback_queryset.count()

    total_recommendations = feedback_queryset.filter(
        would_recommend=True,
    ).count()

    average_rating = feedback_queryset.aggregate(
        average=Avg("rating"),
    )["average"]

    rating_breakdown = (
        feedback_queryset
        .values("rating")
        .annotate(
            count=Count("id"),
        )
        .order_by("-rating")
    )

    feedback = feedback_queryset.order_by(
        "-created_at",
    )[:20]

    context = {
        "total_feedback": total_feedback,
        "total_recommendations": total_recommendations,
        "average_rating": average_rating,
        "rating_breakdown": rating_breakdown,
        "feedback": feedback,
    }

    return render(
        request,
        "feedback/dashboard.html",
        context,
    )
