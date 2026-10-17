import base64
import io

from PIL import Image

from providers.studio import StudioProvider
from tools.contracts.studio import ConversationInput, MusicInput, Scene, Storyboard
from tools.conversations import ground_references


def plan(*scenes):
    return Storyboard(
        project_id="p",
        duration_seconds=6,
        scenes=list(scenes),
        music=MusicInput(prompt="Instrumental"),
    )


def scene(sid, refs=(), continuity=None):
    return Scene(
        id=sid,
        objective="Show it",
        editorial_duration_seconds=2,
        visual_prompt="A product on a table",
        reference_artifact_ids=list(refs),
        continuity_from_scene_id=continuity,
    )


def test_ignored_attachments_are_added_to_scenes_that_start_fresh():
    story = plan(scene("a", ["art_old"]), scene("b", continuity="a"), scene("c", ["x", "y", "z"]))
    ground_references(story, ["art_new"])
    assert story.scenes[0].reference_artifact_ids == ["art_new", "art_old"]
    assert story.scenes[1].reference_artifact_ids == []  # Starts from scene a's last frame.
    assert story.scenes[2].reference_artifact_ids == ["art_new", "x", "y"]


def test_director_placement_of_attachments_is_kept():
    story = plan(scene("a", ["art_new"]), scene("b"), scene("c"))
    ground_references(story, ["art_new"])
    assert [s.reference_artifact_ids for s in story.scenes] == [["art_new"], [], []]


def test_director_sees_attached_and_storyboard_reference_images(runtime, alice, project, submit):
    artifacts = []
    for key in ("first", "second"):
        job = submit(key)
        runtime.worker.execute(project, job.job_id)
        artifacts.append(runtime.commands.get_job(alice, project, job.job_id).artifact_ids[0])
    request = ConversationInput(
        instruction="Make a video about this product",
        reference_artifact_ids=[artifacts[0]],
        context={"storyboard": {"scenes": [{"reference_artifact_ids": [artifacts[1], artifacts[0]]}]}},
    )
    provider = StudioProvider(runtime.commands, "director_turn")
    images = provider.reference_images(request, {"caller": alice.model_dump(), "project_id": project})
    assert [i["artifact_id"] for i in images] == artifacts
    for image in images:
        decoded = Image.open(io.BytesIO(base64.b64decode(image["data"])))
        assert decoded.format == "JPEG" and max(decoded.size) <= 512
