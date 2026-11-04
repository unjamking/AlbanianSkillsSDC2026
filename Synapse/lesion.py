"""The lesion engine: what loses blood when some pipes are blocked. The blood rules live here only."""


class Lesion:
    def __init__(self, atlas, blocked):
        self.atlas = atlas
        # Rule 1: the heart can never be blocked
        self.blocked = [pipe for pipe in atlas.pipes.values() if pipe in blocked and pipe is not atlas.heart]
        self.blood_from = self._flow(use_bridges=True)
        self.pipes_without_blood = [pipe for pipe in atlas.pipes.values() if pipe not in self.blood_from]
        self.stopped_areas = [area for area in atlas.areas.values() if not self._works(area)]
        self.symptoms = []
        for area in self.stopped_areas:
            for symptom in area.symptoms:
                if symptom not in self.symptoms:
                    self.symptoms.append(symptom)
        without_bridges = self._flow(use_bridges=False)
        self.saved_by_bridge = [pipe for pipe in atlas.pipes.values()
                                if pipe in self.blood_from and pipe not in without_bridges]

    def _flow(self, use_bridges):
        heart = self.atlas.heart
        blood_from = {heart: None}  # every pipe with blood -> the pipe its blood came from
        todo = [heart]
        while todo:
            pipe = todo.pop()
            next_pipes = pipe.children
            if use_bridges:
                next_pipes = next_pipes + pipe.bridges
            for next_pipe in next_pipes:
                # Rule 2: a blocked pipe has no blood. Rule 3: one parent (or bridge) with blood is enough.
                if next_pipe not in blood_from and next_pipe not in self.blocked:
                    blood_from[next_pipe] = pipe
                    todo.append(next_pipe)
        return blood_from

    def _works(self, area):
        # Rule 4: an area works if at least one of its pipes has blood
        return any(pipe in self.blood_from for pipe in area.pipes)

    def status(self, item):
        if item in self.blocked:
            return "BLOCKED"
        if item in self.pipes_without_blood:
            return "no blood"
        if item in self.stopped_areas:
            return "stops working"
        return ""


def risky_pipes(atlas, area):
    return [pipe for pipe in atlas.pipes.values()
            if pipe is not atlas.heart and area in Lesion(atlas, [pipe]).stopped_areas]
