from app.schemas import PLATE_LEN, CharRead, FrameRead, RegistryRow


def make_frame(frame_id, plate, conf=0.9, unread=(), overrides=None, sharpness=1.0, area=1.0):
    """Build a FrameRead from a 10-char plate. `unread` slots become None;
    `overrides` maps slot -> (char, conf) to simulate a misread."""
    overrides = overrides or {}
    chars = []
    for i in range(PLATE_LEN):
        if i in unread:
            chars.append(None)
        elif i in overrides:
            ch, c = overrides[i]
            chars.append(CharRead(char=ch, conf=c))
        else:
            chars.append(CharRead(char=plate[i], conf=conf))
    return FrameRead(frame_id=frame_id, sharpness=sharpness, plate_area=area, chars=chars)


def row(reg_id, plate, colour="white", body="suv", flags=()):
    return RegistryRow(reg_id=reg_id, plate=plate, colour=colour, body_type=body,
                       make="Test", model="Car", flags=list(flags))
